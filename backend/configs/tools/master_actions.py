"""Write tools for creating master data from the Dashboard chat: finished products, purchased materials, suppliers.

Used only by the deterministic nodes of `configs/workflows/master_data_graph.py` (never offered to the retrieval
planner). The flow for every entity is the same:

    1. apply_parsed()  -> merge what the user typed into the form values (names are matched against the DB)
    2. form_block()    -> the form shown in the chat (values + inline errors + dropdown options)
    3. validate()      -> check every rule, return (proposal, errors)
    4. execute()       -> create everything in ONE transaction by calling the existing master-data services

Form values (what the frontend sends back), per entity:

    product : {sku, name, uom, selling_price, specification,
               components: [{material_id | new_material, qty}]}
    material: {sku, name, uom, initial_stock, safety_stock,
               suppliers:  [{supplier_id | new_supplier, unit_price, lead_time_days, moq, is_preferred}]}
    supplier: {code, name, contact, payment_term_days,
               materials:  [{material_id | new_material, unit_price, lead_time_days, moq, is_preferred}]}

    new_material = {sku, name, uom, initial_stock, safety_stock,
                    supplier_id? | new_supplier?, unit_price?, lead_time_days?}   (supplier part: product form only)
    new_supplier = {code, name, contact, payment_term_days}
"""
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import Material, Supplier
from app.models.enums import ItemCategory
from app.schemas.material import MaterialCreate, MaterialSupplierCreate
from app.schemas.product import ProductCreate
from app.schemas.supplier import SupplierCreate
from app.services import bom_service, inventory_service, master_service
from configs.tools.curated import resolve_materials
from configs.tools.po_common import fmt_qty, rupiah
from configs.tools.po_resolve import _find_suppliers

ENTITIES = ("product", "material", "supplier")
ROWS_KEY = {"product": "components", "material": "suppliers", "supplier": "materials"}
OPERATION = {"product": "new_product", "material": "new_material", "supplier": "new_supplier"}
TITLE = {"product": "Produk final baru", "material": "Material beli baru", "supplier": "Supplier baru"}
PAGE = {"product": ("/products", "Produk Final"), "material": ("/materials", "Material Beli"),
        "supplier": ("/suppliers", "Supplier")}
BOM_CHILD = (ItemCategory.PURCHASED, ItemCategory.SUB_PART)    # produk final tidak boleh jadi komponen BOM
MAX_ROWS = 30
DEFAULT_UOM = "Buah"


# ------------------------------------------------------------------ empty values
def empty_new_material(name: str = "") -> dict:
    return {"sku": "", "name": name, "uom": DEFAULT_UOM, "initial_stock": 0, "safety_stock": 0,
            "supplier_id": None, "new_supplier": None, "unit_price": None, "lead_time_days": None}


def empty_new_supplier(name: str = "") -> dict:
    return {"code": "", "name": name, "contact": "", "payment_term_days": 0}


def empty_values(entity: str) -> dict:
    """Starting values of a form (defaults: UoM, stock 0, payment term 0)."""
    if entity == "product":
        return {"sku": "", "name": "", "uom": "Unit", "selling_price": None, "specification": "", "components": []}
    if entity == "material":
        return {"sku": "", "name": "", "uom": DEFAULT_UOM, "initial_stock": 0, "safety_stock": 0, "suppliers": []}
    return {"code": "", "name": "", "contact": "", "payment_term_days": 0, "materials": []}


# ------------------------------------------------------------------ step 1: merge parsed text into the form
SCALAR_FIELDS = {
    "product": ("sku", "name", "uom", "selling_price", "specification"),
    "material": ("sku", "name", "uom", "initial_stock", "safety_stock"),
    "supplier": ("code", "name", "contact", "payment_term_days"),
}


def _material_matches(db: Session, entity: str, query: str) -> list[Material]:
    """Existing, active materials the user may mean (BOM: purchased + sub-part; supplier: purchased only).

    Only matches that contain every typed word count: a merely similar name ("Bel Sepeda" ~ "Pedal Sepeda")
    is treated as a NEW material, because here a wrong match would silently reuse another item.
    """
    categories = BOM_CHILD if entity == "product" else (ItemCategory.PURCHASED,)
    words = [w.lower() for w in query.split()]

    def contains_all_words(m: Material) -> bool:
        text = f"{m.sku} {m.name}".lower()
        return all(w in text for w in words)

    return [m for m in resolve_materials(db, query, categories) if m.is_active and contains_all_words(m)]


def _new_row(entity: str, item: dict) -> dict:
    """A form row for one parsed item, with nothing selected yet."""
    if entity == "product":
        return {"material_id": None, "new_material": None, "qty": item.get("qty")}
    row = {"unit_price": item.get("unit_price"), "lead_time_days": item.get("lead_time_days"),
           "moq": item.get("moq") or 1, "is_preferred": False}
    if entity == "material":
        return {"supplier_id": None, "new_supplier": None, **row}
    return {"material_id": None, "new_material": None, **row}


def _resolve_item(db: Session, entity: str, item: dict) -> tuple[dict, str | None]:
    """Turns one typed name into a form row: 1 match -> selected, 0 -> a new item, >1 -> the user must pick.

    Returns (row, error message or None).
    """
    query = (item.get("query") or "").strip()
    row = _new_row(entity, item)
    if entity == "material":                                  # baris = supplier
        matches = _find_suppliers(db, query)
        if len(matches) == 1:
            row["supplier_id"] = matches[0].id
        elif not matches:
            row["new_supplier"] = empty_new_supplier(query)
        else:
            names = ", ".join(f"{s.code} {s.name}" for s in matches[:5])
            return row, f"'{query}' cocok dengan beberapa supplier ({names}). Pilih salah satu."
        return row, None
    matches = _material_matches(db, entity, query)            # baris = material
    if len(matches) == 1:
        row["material_id"] = matches[0].id
    elif not matches:
        row["new_material"] = empty_new_material(query)
    else:
        names = ", ".join(f"{m.sku} {m.name}" for m in matches[:5])
        return row, f"'{query}' cocok dengan beberapa material ({names}). Pilih salah satu."
    return row, None


def _row_id(entity: str, row: dict) -> int | None:
    return row.get("supplier_id") if entity == "material" else row.get("material_id")


def apply_parsed(db: Session, entity: str, values: dict, fields: dict, items: list[dict]) -> tuple[dict, dict]:
    """Merges what the parser extracted into `values`. Returns (new values, errors for ambiguous names).

    Typed fields overwrite the form; typed items update a row that already holds the same record, otherwise
    they are appended as new rows.
    """
    values = {**empty_values(entity), **(values or {})}
    for key in SCALAR_FIELDS[entity]:
        if fields.get(key) not in (None, ""):
            values[key] = fields[key]
    rows_key = ROWS_KEY[entity]
    rows = [dict(r) for r in values.get(rows_key) or []]
    errors = {}
    for item in items or []:
        if not (item.get("query") or "").strip():
            continue
        row, error = _resolve_item(db, entity, item)
        same = [r for r in rows if _row_id(entity, row) is not None and _row_id(entity, r) == _row_id(entity, row)]
        if same:                                              # rekaman sama sudah ada di form -> perbarui angkanya
            for key, value in row.items():
                if value is not None and key not in ("new_material", "new_supplier"):
                    same[0][key] = value
            continue
        rows.append(row)
        if error:
            errors[f"{rows_key}.{len(rows) - 1}.{'supplier_id' if entity == 'material' else 'material_id'}"] = error
    values[rows_key] = rows[:MAX_ROWS]
    return values, errors


# ------------------------------------------------------------------ step 2: the form block
def _latest(db: Session, column, *where) -> str | None:
    """Latest existing SKU/code, shown as an example placeholder in the form."""
    return db.scalar(select(column).where(*where).order_by(column.desc()).limit(1))


def form_options(db: Session, entity: str) -> dict:
    """Dropdown choices for the form rows (active records only)."""
    categories = BOM_CHILD if entity == "product" else (ItemCategory.PURCHASED,)
    materials = db.scalars(select(Material).where(Material.is_active, Material.category.in_(categories))
                           .order_by(Material.sku)).all()
    suppliers = db.scalars(select(Supplier).where(Supplier.is_active).order_by(Supplier.code)).all()
    return {
        "materials": [{"value": m.id, "label": f"{m.sku} · {m.name}", "uom": m.uom,
                       "category": m.category.value} for m in materials],
        "suppliers": [{"value": s.id, "label": f"{s.code} · {s.name}"} for s in suppliers],
    }


def form_hints(db: Session) -> dict:
    """Example placeholders, e.g. the latest SKU of each kind."""
    return {
        "product_sku": _latest(db, Material.sku, Material.category == ItemCategory.FINISHED) or "FG-XXX-01",
        "material_sku": _latest(db, Material.sku, Material.category == ItemCategory.PURCHASED) or "RM-XXX-01",
        "supplier_code": _latest(db, Supplier.code) or "SUP-XXX",
    }


def form_block(db: Session, form_id: str, entity: str, values: dict, errors: dict) -> dict:
    """The `form` chat block rendered by the frontend (`features/chat/ChatForm.jsx`)."""
    return {"type": "form", "formId": form_id, "entity": entity, "title": TITLE[entity],
            "submitLabel": "Tinjau & lanjutkan", "values": values, "errors": errors,
            "emptyValues": empty_values(entity),              # untuk tombol "Kosongkan formulir"
            "options": form_options(db, entity), "hints": form_hints(db)}


# ------------------------------------------------------------------ step 3: validation
FRIENDLY = {
    "missing": "Wajib diisi",
    "string_too_short": "Wajib diisi (minimal {min_length} karakter)",
    "string_too_long": "Maksimal {max_length} karakter",
    "greater_than_equal": "Minimal {ge}",
    "greater_than": "Harus lebih dari {gt}",
    "less_than_equal": "Maksimal {le}",
    "int_parsing": "Harus berupa bilangan bulat",
    "int_from_float": "Harus berupa bilangan bulat",
    "float_parsing": "Harus berupa angka",
}


def _clean(value):
    """Trims strings; empty strings become None (so Pydantic reports a missing value)."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _check_schema(schema: type[BaseModel], data: dict, prefix: str, errors: dict) -> dict | None:
    """Validates `data` with an existing API schema; errors are stored under `prefix.field`."""
    data = {k: v for k, v in ((k, _clean(v)) for k, v in data.items()) if v is not None}
    try:
        return schema(**data).model_dump()
    except ValidationError as e:
        for err in e.errors():
            field = ".".join(str(p) for p in err["loc"])
            text = FRIENDLY.get(err["type"], err["msg"]).format(**(err.get("ctx") or {}))
            errors.setdefault(f"{prefix}{field}", text)
        return None


def _number(value, path: str, errors: dict, *, minimum: float = 0, integer: bool = False,
            required: bool = True, above: bool = False):
    """Reads a number from the form (None when empty and optional)."""
    value = _clean(value)
    if value is None:
        if required:
            errors[path] = "Wajib diisi"
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors[path] = "Harus berupa angka"
        return None
    if integer and number != int(number):
        errors[path] = "Harus berupa bilangan bulat"
        return None
    if number < minimum or (above and number == minimum):
        errors[path] = f"Harus lebih dari {fmt_qty(minimum)}" if above else f"Minimal {fmt_qty(minimum)}"
        return None
    return int(number) if integer else number


class _Plan:
    """Everything a confirmed form will create, collected while validating."""

    def __init__(self):
        self.new_suppliers: list[dict] = []   # data for master_service.create_supplier
        self.new_materials: list[dict] = []   # data for create_material + {initial_stock, safety_stock}
        self.product: dict | None = None
        self.bom: list[dict] = []             # {child: ref, qty}
        self.links: list[dict] = []           # {material: ref, supplier: ref, unit_price, lead_time_days, moq, is_preferred}
        self.labels: dict[str, str] = {}      # ref key -> "SKU nama" for the card

    @staticmethod
    def key(kind: str, value) -> str:
        """Reference to an existing (`mat:12`) or a new (`new-mat:RM-X`) record."""
        return f"{kind}:{value}"


def _sku_taken(db: Session, sku: str) -> bool:
    return db.scalar(select(Material.id).where(Material.sku == sku).limit(1)) is not None


def _code_taken(db: Session, code: str) -> bool:
    return db.scalar(select(Supplier.id).where(Supplier.code == code).limit(1)) is not None


def _add_new_material(db: Session, plan: _Plan, data: dict, path: str, errors: dict, seen_skus: set) -> str | None:
    """Validates one new purchased material; returns its reference key or None."""
    checked = _check_schema(MaterialCreate, {k: data.get(k) for k in ("sku", "name", "uom")}, f"{path}.", errors)
    initial = _number(data.get("initial_stock", 0), f"{path}.initial_stock", errors, required=False) or 0
    safety = _number(data.get("safety_stock", 0), f"{path}.safety_stock", errors, required=False) or 0
    if checked is None:
        return None
    sku = checked["sku"]
    if sku.upper() in seen_skus:
        errors[f"{path}.sku"] = f"SKU '{sku}' dipakai lebih dari sekali di formulir ini"
        return None
    seen_skus.add(sku.upper())
    if _sku_taken(db, sku):
        errors[f"{path}.sku"] = f"SKU '{sku}' sudah terdaftar"
        return None
    key = plan.key("new-mat", sku)
    plan.new_materials.append({**checked, "initial_stock": initial, "safety_stock": safety, "key": key})
    plan.labels[key] = f"{sku} {checked['name']} (baru)"
    return key


def _add_new_supplier(db: Session, plan: _Plan, data: dict, path: str, errors: dict, seen_codes: set) -> str | None:
    """Validates one new supplier; returns its reference key or None."""
    fields = {k: data.get(k) for k in ("code", "name", "contact", "payment_term_days")}
    checked = _check_schema(SupplierCreate, fields, f"{path}.", errors)
    if checked is None:
        return None
    code = checked["code"]
    if code.upper() in seen_codes:
        errors[f"{path}.code"] = f"Kode '{code}' dipakai lebih dari sekali di formulir ini"
        return None
    seen_codes.add(code.upper())
    if _code_taken(db, code):
        errors[f"{path}.code"] = f"Kode supplier '{code}' sudah terdaftar"
        return None
    key = plan.key("new-sup", code)
    plan.new_suppliers.append({**checked, "key": key})
    plan.labels[key] = f"{code} {checked['name']} (baru)"
    return key


def _existing_material(db: Session, plan: _Plan, material_id, path: str, errors: dict,
                       allowed: tuple[ItemCategory, ...]) -> str | None:
    """Checks a material picked from the dropdown; returns its reference key or None."""
    m = db.get(Material, int(material_id)) if str(material_id).isdigit() else None
    if m is None:
        errors[path] = "Material tidak ditemukan"
        return None
    if not m.is_active:
        errors[path] = f"{m.sku} tidak aktif"
        return None
    if m.category not in allowed:
        is_bom = allowed == BOM_CHILD
        errors[path] = ("Produk Final tidak dapat menjadi komponen BOM; gunakan material beli atau sub-part"
                        if is_bom else f"{m.sku} bukan material beli")
        return None
    key = plan.key("mat", m.id)
    plan.labels[key] = f"{m.sku} {m.name}"
    return key


def _existing_supplier(db: Session, plan: _Plan, supplier_id, path: str, errors: dict) -> str | None:
    s = db.get(Supplier, int(supplier_id)) if str(supplier_id).isdigit() else None
    if s is None or not s.is_active:
        errors[path] = "Supplier tidak ditemukan atau tidak aktif"
        return None
    key = plan.key("sup", s.id)
    plan.labels[key] = f"{s.code} {s.name}"
    return key


def _link_terms(row: dict, path: str, errors: dict) -> dict | None:
    """Price / lead time / MOQ of a material-supplier link, checked with `MaterialSupplierCreate`."""
    price = _number(row.get("unit_price"), f"{path}.unit_price", errors, integer=True)
    lead = _number(row.get("lead_time_days"), f"{path}.lead_time_days", errors, integer=True)
    moq = _number(row.get("moq") if row.get("moq") not in (None, "") else 1, f"{path}.moq", errors, above=True)
    if None in (price, lead, moq):
        return None
    terms = {"supplier_id": 0, "unit_price": price, "lead_time_days": lead, "moq": moq,
             "is_preferred": bool(row.get("is_preferred"))}
    checked = _check_schema(MaterialSupplierCreate, terms, f"{path}.", errors)
    return None if checked is None else {k: v for k, v in checked.items() if k != "supplier_id"}


def _validate_product(db: Session, v: dict, plan: _Plan, errors: dict) -> None:
    fields = {k: v.get(k) for k in SCALAR_FIELDS["product"]}
    product = _check_schema(ProductCreate, fields, "", errors)
    seen_skus, seen_codes, seen_ids = set(), set(), set()
    sku = _clean(v.get("sku"))
    if isinstance(sku, str) and "sku" not in errors:          # cek SKU walau kolom lain masih salah
        seen_skus.add(sku.upper())
        if _sku_taken(db, sku):
            errors["sku"] = f"SKU '{sku}' sudah terdaftar"
    plan.product = product
    for i, row in enumerate(v.get("components") or []):
        path = f"components.{i}"
        qty = _number(row.get("qty"), f"{path}.qty", errors, above=True)
        if row.get("new_material"):
            new = row["new_material"]
            child = _add_new_material(db, plan, new, f"{path}.new_material", errors, seen_skus)
            # opsional: material baru langsung diikat ke supplier yang ada ATAU ke supplier baru
            sup = None
            if new.get("new_supplier"):
                sup = _add_new_supplier(db, plan, new["new_supplier"], f"{path}.new_material.new_supplier", errors,
                                        seen_codes)
            elif _clean(new.get("supplier_id")) is not None:
                sup = _existing_supplier(db, plan, new["supplier_id"], f"{path}.new_material.supplier_id", errors)
            if new.get("new_supplier") or _clean(new.get("supplier_id")) is not None:
                terms = _link_terms(new, f"{path}.new_material", errors)
                if child and sup and terms:
                    plan.links.append({"material": child, "supplier": sup, **terms})
        elif _clean(row.get("material_id")) is not None:
            child = _existing_material(db, plan, row["material_id"], f"{path}.material_id", errors, BOM_CHILD)
            if child in seen_ids:
                errors[f"{path}.material_id"] = "Komponen ini sudah ada di baris lain"
                child = None
            seen_ids.add(child)
        else:
            errors[f"{path}.material_id"] = "Pilih material atau tambah material baru"
            child = None
        if child and qty:
            plan.bom.append({"child": child, "qty": qty})


def _validate_material(db: Session, v: dict, plan: _Plan, errors: dict) -> None:
    seen_skus, seen_codes, seen_ids = set(), set(), set()
    main = _add_new_material(db, plan, v, "", errors, seen_skus)
    for key in ("sku", "name", "uom", "initial_stock", "safety_stock"):   # path "" -> ".sku"; rapikan
        if f".{key}" in errors:
            errors[key] = errors.pop(f".{key}")
    for i, row in enumerate(v.get("suppliers") or []):
        path = f"suppliers.{i}"
        if row.get("new_supplier"):
            sup = _add_new_supplier(db, plan, row["new_supplier"], f"{path}.new_supplier", errors, seen_codes)
        elif _clean(row.get("supplier_id")) is not None:
            sup = _existing_supplier(db, plan, row["supplier_id"], f"{path}.supplier_id", errors)
            if sup in seen_ids:
                errors[f"{path}.supplier_id"] = "Supplier ini sudah ada di baris lain"
                sup = None
            seen_ids.add(sup)
        else:
            errors[f"{path}.supplier_id"] = "Pilih supplier atau tambah supplier baru"
            sup = None
        terms = _link_terms(row, path, errors)
        if main and sup and terms:
            plan.links.append({"material": main, "supplier": sup, **terms})


def _validate_supplier(db: Session, v: dict, plan: _Plan, errors: dict) -> None:
    seen_skus, seen_codes, seen_ids = set(), set(), set()
    main = _add_new_supplier(db, plan, v, "", errors, seen_codes)
    for key in ("code", "name", "contact", "payment_term_days"):
        if f".{key}" in errors:
            errors[key] = errors.pop(f".{key}")
    for i, row in enumerate(v.get("materials") or []):
        path = f"materials.{i}"
        if row.get("new_material"):
            mat = _add_new_material(db, plan, row["new_material"], f"{path}.new_material", errors, seen_skus)
        elif _clean(row.get("material_id")) is not None:
            mat = _existing_material(db, plan, row["material_id"], f"{path}.material_id", errors,
                                     (ItemCategory.PURCHASED,))
            if mat in seen_ids:
                errors[f"{path}.material_id"] = "Material ini sudah ada di baris lain"
                mat = None
            seen_ids.add(mat)
        else:
            errors[f"{path}.material_id"] = "Pilih material atau tambah material baru"
            mat = None
        terms = _link_terms(row, path, errors)
        if main and mat and terms:
            plan.links.append({"material": mat, "supplier": main, **terms})


def _warnings(entity: str, plan: _Plan) -> list[str]:
    """Things that are allowed but limit what the new data can be used for."""
    out = []
    if entity == "product" and not plan.bom:
        out.append("Produk belum punya BOM, jadi belum bisa dijadwalkan produksi. Tambahkan komponen di halaman BOM.")
    linked = {link["material"] for link in plan.links}
    no_supplier = [m["sku"] for m in plan.new_materials if m["key"] not in linked]
    if no_supplier:
        out.append(f"Material baru tanpa supplier ({', '.join(no_supplier)}) belum bisa dibuatkan PO. "
                   "Hubungkan supplier di halaman Material.")
    if entity == "supplier" and not plan.links:
        out.append("Supplier belum terhubung ke material apa pun.")
    return out


def validate(db: Session, entity: str, values: dict) -> tuple[dict | None, dict]:
    """Checks a submitted form. Returns (proposal, {}) when valid, else (None, {field path: message})."""
    if entity not in ENTITIES:
        return None, {"_form": "Jenis data tidak dikenal"}
    rows = values.get(ROWS_KEY[entity]) or []
    if len(rows) > MAX_ROWS:
        return None, {"_form": f"Maksimal {MAX_ROWS} baris"}
    plan, errors = _Plan(), {}
    {"product": _validate_product, "material": _validate_material, "supplier": _validate_supplier}[entity](
        db, values, plan, errors)
    if errors:
        return None, errors
    proposal = {"operation": OPERATION[entity], "entity": entity, "request": values,
                "new_suppliers": plan.new_suppliers, "new_materials": plan.new_materials, "product": plan.product,
                "bom": plan.bom, "links": plan.links, "labels": plan.labels, "warnings": _warnings(entity, plan)}
    return proposal, {}


# ------------------------------------------------------------------ confirmation card
def _table(title: str, columns: list[str], rows: list[list]) -> dict:
    return {"type": "table", "title": title, "columns": columns, "rows": rows}


def proposal_tables(p: dict) -> list[dict]:
    """Tables shown in the confirmation card: main data, new items, BOM, supplier links."""
    label = p["labels"].get
    tables = []
    if p["product"]:
        pr = p["product"]
        tables.append(_table("Produk final", ["SKU", "Nama", "Satuan", "Harga jual", "Spesifikasi"],
                             [[pr["sku"], pr["name"], pr["uom"], rupiah(pr["selling_price"]),
                               pr.get("specification") or "–"]]))
    if p["new_materials"]:
        tables.append(_table("Material beli baru", ["SKU", "Nama", "Satuan", "Stok awal", "Safety stock"],
                             [[m["sku"], m["name"], m["uom"], fmt_qty(m["initial_stock"]),
                               fmt_qty(m["safety_stock"])] for m in p["new_materials"]]))
    if p["new_suppliers"]:
        tables.append(_table("Supplier baru", ["Kode", "Nama", "Kontak", "Termin"],
                             [[s["code"], s["name"], s.get("contact") or "–", f"Net {s['payment_term_days']}"]
                              for s in p["new_suppliers"]]))
    if p["bom"]:
        tables.append(_table("Komponen BOM (per 1 unit produk)", ["Komponen", "Qty"],
                             [[label(b["child"], b["child"]), fmt_qty(b["qty"])] for b in p["bom"]]))
    if p["links"]:
        tables.append(_table("Relasi material–supplier", ["Material", "Supplier", "Harga", "Lead time", "MOQ",
                                                          "Preferred"],
                             [[label(l["material"], l["material"]), label(l["supplier"], l["supplier"]),
                               rupiah(l["unit_price"]), f"{l['lead_time_days']} hari", fmt_qty(l["moq"]),
                               "Ya" if l["is_preferred"] else "–"] for l in p["links"]]))
    return tables


def main_label(p: dict) -> str:
    """'FG-X Nama' of the record the form is about."""
    if p["entity"] == "product":
        return f"{p['product']['sku']} {p['product']['name']}"
    if p["entity"] == "material":
        return f"{p['new_materials'][0]['sku']} {p['new_materials'][0]['name']}"
    return f"{p['new_suppliers'][0]['code']} {p['new_suppliers'][0]['name']}"


def action_card(action_id: str, p: dict, status: str = "pending") -> dict:
    counts = []
    if p["new_materials"]:
        counts.append(f"{len(p['new_materials'])} material baru")
    if p["new_suppliers"]:
        counts.append(f"{len(p['new_suppliers'])} supplier baru")
    if p["bom"]:
        counts.append(f"{len(p['bom'])} komponen BOM")
    if p["links"]:
        counts.append(f"{len(p['links'])} relasi supplier")
    return {"id": action_id, "kind": p["operation"], "title": f"Simpan {TITLE[p['entity']].lower()}: {main_label(p)}",
            "detail": "Akan dibuat dalam satu transaksi: " + (", ".join(counts) or "data utama saja") + ".",
            "approveLabel": "Konfirmasi & simpan", "status": status, "tables": proposal_tables(p),
            "warnings": p.get("warnings") or []}


# ------------------------------------------------------------------ step 4: execute (one transaction)
def execute(db: Session, proposal: dict) -> dict:
    """Creates everything in the proposal using the existing services.

    Call inside `po_actions.write_session()`: the services commit after each step, which there only releases a
    savepoint, so all records are written together or not at all. The form is validated again first, because
    data may have changed since the card was shown (e.g. someone registered the same SKU).
    """
    fresh, errors = validate(db, proposal["entity"], proposal["request"])
    if errors:
        raise AppError(409, "Data berubah sejak usulan dibuat: " + "; ".join(errors.values()))

    ids: dict[str, int] = {}                 # reference key -> new database id
    for s in fresh["new_suppliers"]:
        data = {k: s[k] for k in ("code", "name", "contact", "payment_term_days")}
        ids[s["key"]] = master_service.create_supplier(db, data).id
    for m in fresh["new_materials"]:
        material = master_service.create_material(db, {k: m[k] for k in ("sku", "name", "uom")})
        ids[m["key"]] = material.id
        inventory_service.get_or_create_inventory(db, material.id)        # agar muncul di halaman Inventory
        if m["initial_stock"] or m["safety_stock"]:
            inventory_service.update_inventory(db, material.id, m["initial_stock"], m["safety_stock"])
    product_id = None
    if fresh["product"]:
        product_id = master_service.create_product(db, dict(fresh["product"]))["id"]
    for b in fresh["bom"]:
        bom_service.add_item(db, product_id, _ref_id(b["child"], ids), b["qty"])
    for link in fresh["links"]:
        terms = {k: link[k] for k in ("unit_price", "lead_time_days", "moq", "is_preferred")}
        master_service.add_link(db, _ref_id(link["material"], ids),
                                {"supplier_id": _ref_id(link["supplier"], ids), **terms})
    return {"entity": fresh["entity"], "product_id": product_id, "created_ids": ids,
            "summary": {"materials": len(fresh["new_materials"]), "suppliers": len(fresh["new_suppliers"]),
                        "bom": len(fresh["bom"]), "links": len(fresh["links"])},
            "label": main_label(fresh)}


def _ref_id(ref: str, new_ids: dict[str, int]) -> int:
    """`mat:12` / `sup:3` -> 12 / 3; `new-mat:RM-X` -> the id just created."""
    if ref in new_ids:
        return new_ids[ref]
    return int(ref.split(":", 1)[1])


def result_text(result: dict) -> str:
    s = result["summary"]
    parts = [f"{TITLE[result['entity']]} {result['label']} berhasil disimpan."]
    extra = []
    if s["materials"] and result["entity"] != "material":
        extra.append(f"{s['materials']} material baru")
    elif s["materials"] > 1:
        extra.append(f"{s['materials'] - 1} material baru lain")
    if s["suppliers"] and result["entity"] != "supplier":
        extra.append(f"{s['suppliers']} supplier baru")
    if s["bom"]:
        extra.append(f"{s['bom']} komponen BOM")
    if s["links"]:
        extra.append(f"{s['links']} relasi material–supplier")
    if extra:
        parts.append("Ikut dibuat: " + ", ".join(extra) + ".")
    return " ".join(parts)


def result_links(result: dict) -> list[dict]:
    """Link blocks to the pages where the new data now appears."""
    to, page = PAGE[result["entity"]]
    links = [{"type": "link", "to": to, "label": f"Lihat di halaman {page}"}]
    if result["entity"] == "product" and result["summary"]["bom"]:
        links.append({"type": "link", "to": "/bom", "label": "Lihat BOM"})
    if result["summary"]["materials"] and result["entity"] != "material":
        links.append({"type": "link", "to": "/materials", "label": "Lihat material baru"})
    if result["summary"]["suppliers"] and result["entity"] != "supplier":
        links.append({"type": "link", "to": "/suppliers", "label": "Lihat supplier baru"})
    return links


MASTER_WRITE_TOOLS = {
    "apply_parsed": apply_parsed,
    "form_block": form_block,
    "validate_master_data": validate,
    "execute_master_data": execute,
}
