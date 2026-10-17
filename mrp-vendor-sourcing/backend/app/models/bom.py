from sqlalchemy import ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BOMItem(Base):
    __tablename__ = "bom_items"
    __table_args__ = (
        UniqueConstraint("parent_id", "child_id"),
        CheckConstraint("qty_per_parent > 0"),
        CheckConstraint("parent_id != child_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), index=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), index=True)
    qty_per_parent: Mapped[float]

    parent: Mapped["Material"] = relationship(foreign_keys=[parent_id])
    child: Mapped["Material"] = relationship(foreign_keys=[child_id])

    # properti bantu untuk schema output
    @property
    def child_sku(self) -> str:
        return self.child.sku

    @property
    def child_name(self) -> str:
        return self.child.name

    @property
    def child_uom(self) -> str:
        return self.child.uom

    @property
    def child_category(self):
        return self.child.category
