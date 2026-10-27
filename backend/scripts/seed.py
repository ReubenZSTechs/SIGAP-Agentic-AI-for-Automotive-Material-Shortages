"""Enterprise automotive MRP seed data (21 vehicle models incl. SokratesCar, 4-level BOM, 36 suppliers).

Usage (from the project root):
    python -m scripts.seed                    # populate an empty database
    python -m scripts.seed --demo-schedules   # + demo schedules (nearest Monday: 30 units, Tuesday: 20 units)
    python -m scripts.seed --reset            # drop all tables, then re-seed

BOM depth (every branch reaches PURCHASED material):
    FINISHED vehicle -> SUB_PART module (Powertrain / Body & Chassis / Interior / Electrical & Battery)
                     -> SUB_PART assembly (engine, transmission, e-drive, battery pack, brake, seat set ...)
                     -> PURCHASED component (block, cell, ECU, wheel, harness ...)
Battery branch is 5 levels deep: Vehicle -> Pack -> Cell Module -> Cell.

Assumptions:
  * Quantities are per ONE parent unit; "Set"-UOM parts are purchased/stocked as complete sets.
  * The first supplier listed for each SKU in SOURCING is flagged is_preferred=True.
  * Prices are Rupiah (IDR) per purchasing UOM; lead times in calendar days.
  * All supplier names, contacts and prices are fictitious dummy data (".example" domains).
"""
import argparse
import os
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.database import Base, SessionLocal, engine
from app.models import (BOMItem, Inventory, Material, MaterialSupplier, ProductionLine, Supplier)
from app.models.enums import ItemCategory

FIN, SUB, BUY = ItemCategory.FINISHED, ItemCategory.SUB_PART, ItemCategory.PURCHASED

# Telegram chat_id for the two SokratesCar test suppliers (Supplier has no telegram column, so it is stored
# inside `contact`). Set env vars before seeding:  TELEGRAM_CHAT_ID_FANDI=123456789  TELEGRAM_CHAT_ID_CHRIS=987654321
TG_FANDI = os.getenv("TELEGRAM_CHAT_ID_FANDI", "ISI_CHAT_ID_FANDI")
TG_CHRIS = os.getenv("TELEGRAM_CHAT_ID_CHRIS", "ISI_CHAT_ID_CHRIS")

# code, name, contact
SUPPLIERS = [
    # ---- Indonesian (local) suppliers ----
    ("SUP-NPC", "PT Nusantara Powertrain Components", "Hendra Wijaya | +62 21 8908 1100 | sales@nusantara-powertrain.example"),
    ("SUP-JBC", "PT Jababeka Casting Industri", "Agus Prasetyo | +62 21 8935 2200 | order@jababeka-casting.example"),
    ("SUP-GAM", "PT Garuda Auto Metal", "Rini Kusumawati | +62 21 8970 3300 | sales@garuda-autometal.example"),
    ("SUP-MBR", "PT Mandiri Brake & Chassis", "Dedi Hermawan | +62 21 8990 4400 | sales@mandiri-brake.example"),
    ("SUP-WLS", "PT Wahana Alloy Wheels", "Siti Rahmawati | +62 21 8911 5500 | sales@wahana-alloy.example"),
    ("SUP-SGS", "PT Surya Glass Sejahtera", "Budi Hartono | +62 21 8922 6600 | order@suryaglass.example"),
    ("SUP-PTN", "PT Pelita Tekstil Nusantara", "Lestari Dewi | +62 22 6030 7700 | sales@pelita-tekstil.example"),
    ("SUP-BDG", "PT Bandung Seating Systems", "Yusuf Maulana | +62 22 6041 8800 | sales@bandung-seating.example"),
    ("SUP-CWH", "PT Cakra Wiring Harness", "Andi Setiawan | +62 21 8952 9900 | sales@cakra-harness.example"),
    ("SUP-TLM", "PT Tirta Lampu Mobil", "Maria Susanti | +62 21 8963 1010 | sales@tirta-lampu.example"),
    ("SUP-SPR", "PT Sinar Paint & Resin", "Eko Nugroho | +62 21 8974 1111 | order@sinar-paint.example"),
    ("SUP-IPL", "PT Indo Plastik Otomotif", "Wulan Sari | +62 21 8985 1212 | sales@indoplastik-oto.example"),
    # ---- Global suppliers ----
    ("SUP-ZFT", "Zeffer Antriebstechnik GmbH (Germany)", "Klaus Reinhardt | +49 7541 77 1300 | export@zeffer-antrieb.example"),
    ("SUP-BRT", "Brandt Mobility Systems AG (Germany)", "Anna Vogel | +49 711 811 1400 | apac.sales@brandt-mobility.example"),
    ("SUP-DNK", "Denkai Electronics Co., Ltd. (Japan)", "Takeshi Mori | +81 566 22 1500 | overseas@denkai-electronics.example"),
    ("SUP-AIS", "Aishin Drivetrain Corp. (Japan)", "Hiroshi Tanabe | +81 566 25 1600 | export@aishin-drivetrain.example"),
    ("SUP-BWY", "Bridgeway Tyre Co., Ltd. (Japan)", "Kenji Okada | +81 3 5202 1700 | oem@bridgeway-tyre.example"),
    ("SUP-HYT", "Hanyoung Tire Co., Ltd. (South Korea)", "Min-jun Park | +82 2 2222 1800 | oem@hanyoung-tire.example"),
    ("SUP-CAT", "Catalytica Emission Systems Inc. (USA)", "Jason Miller | +1 812 377 1900 | oem@catalytica-emissions.example"),
    ("SUP-LGX", "Lumigen Energy Solutions Co., Ltd. (South Korea)", "Seo-yeon Kim | +82 2 3777 2000 | cells@lumigen-energy.example"),
    ("SUP-ZHB", "Zhonghai Battery Technology Co., Ltd. (China)", "Wei Zhang | +86 593 8900 2100 | export@zhonghai-battery.example"),
    ("SUP-SPC", "Sunrise Power Cells Co., Ltd. (China)", "Li Na | +86 755 2600 2200 | sales@sunrise-powercells.example"),
    ("SUP-PNS", "Panasync Energy Corp. (Japan)", "Ryo Yamada | +81 6 6908 2300 | automotive@panasync-energy.example"),
    ("SUP-VLR", "Valeron Thermal Systems S.A. (France)", "Claire Dubois | +33 1 4000 2400 | oem@valeron-thermal.example"),
    ("SUP-MGN", "Magnus Electric Drives GmbH (Germany)", "Stefan Keller | +49 911 650 2500 | sales@magnus-edrive.example"),
    ("SUP-SHC", "Shanghai Huachen Motor Co., Ltd. (China)", "Chen Hao | +86 21 5800 2600 | export@huachen-motor.example"),
    ("SUP-TRQ", "Torquenova Turbo Systems Ltd. (United Kingdom)", "James Whitfield | +44 1484 55 2700 | oem@torquenova-turbo.example"),
    ("SUP-TCS", "Thai Chassis & Suspension Co., Ltd. (Thailand)", "Somchai Prasert | +66 38 123 280 | sales@thai-chassis.example"),
    ("SUP-AXL", "Axiom Safety Systems Inc. (USA)", "Michael Turner | +1 248 555 2900 | apac@axiom-safety.example"),
    ("SUP-SND", "Sonora Infotainment Co., Ltd. (South Korea)", "Ji-ho Lee | +82 31 700 3000 | oem@sonora-infotainment.example"),
    ("SUP-ADV", "AdaptiveVision Sensors GmbH (Germany)", "Lukas Brandl | +49 89 5500 3100 | adas@adaptivevision.example"),
    ("SUP-ELX", "Elektra Power Electronics B.V. (Netherlands)", "Pieter de Vries | +31 40 250 3200 | sales@elektra-power.example"),
    ("SUP-MKT", "Mekatron Precision Malaysia Sdn Bhd (Malaysia)", "Farid Rahman | +60 3 5569 3300 | sales@mekatron-precision.example"),
    ("SUP-VHM", "Viet Harness Manufacturing JSC (Vietnam)", "Nguyen Van Minh | +84 24 3555 3400 | export@viet-harness.example"),
    # ---- SokratesCar dedicated test suppliers (Telegram integration) ----
    ("SUP-FND", "PT Fandi", f"Fandi | Telegram chat_id: {TG_FANDI}"),
    ("SUP-CHR", "PT Chris", f"Chris | Telegram chat_id: {TG_CHRIS}"),
]

# Plant production lines (label only; no capacity planning)
LINES = [
    ("LINE-BODY-01", "Body Shop - Welding & Framing Line 1"),
    ("LINE-BODY-02", "Body Shop - Welding & Framing Line 2"),
    ("LINE-PAINT-01", "Paint Shop - E-Coat, Primer & Topcoat Line"),
    ("LINE-PT-ICE", "Powertrain Assembly - ICE Engine & Transmission"),
    ("LINE-PT-EV", "e-Powertrain Assembly - Motor, Inverter & e-Axle"),
    ("LINE-BAT-01", "Battery Module & Pack Assembly Line"),
    ("LINE-FA-01", "Final Assembly Line 1 - ICE & Hybrid Passenger Cars"),
    ("LINE-FA-02", "Final Assembly Line 2 - Battery EV & Plug-in Hybrid"),
    ("LINE-FA-03", "Final Assembly Line 3 - Pickup & Light Commercial"),
    ("LINE-EOL-01", "End-of-Line Testing & Quality Gate"),
]

# Payment terms (days) per supplier code; unlisted = 0 (cash on delivery)
TERMS = {
    "SUP-NPC": 30, "SUP-JBC": 30, "SUP-GAM": 45, "SUP-MBR": 30, "SUP-WLS": 30, "SUP-SGS": 30,
    "SUP-PTN": 30, "SUP-BDG": 30, "SUP-CWH": 30, "SUP-TLM": 21, "SUP-IPL": 45,
    "SUP-ZFT": 60, "SUP-BRT": 60, "SUP-DNK": 60, "SUP-AIS": 60, "SUP-BWY": 45, "SUP-HYT": 45,
    "SUP-CAT": 60, "SUP-LGX": 90, "SUP-ZHB": 90, "SUP-SPC": 90, "SUP-PNS": 90, "SUP-VLR": 60,
    "SUP-MGN": 60, "SUP-SHC": 60, "SUP-TRQ": 60, "SUP-TCS": 45, "SUP-AXL": 60, "SUP-SND": 60,
    "SUP-ADV": 60, "SUP-ELX": 60, "SUP-MKT": 14, "SUP-VHM": 45,
    "SUP-FND": 14, "SUP-CHR": 30,
}   # SUP-SPR intentionally omitted -> 0 days (cash)

# sku, name, uom, category (FIN = finished vehicle, SUB = "Made" module/assembly, BUY = purchased component)
MATERIALS = [
    # ===================== FINISHED VEHICLES (20) =====================
    ("FG-HB-ICE-01", "City Hatchback 1.2L CVT", "Unit", FIN),
    ("FG-SDN-ICE-02", "Compact Sedan 1.5L CVT", "Unit", FIN),
    ("FG-SUV-ICE-03", "Compact SUV 1.5L CVT", "Unit", FIN),
    ("FG-SUV-ICE-04", "Midsize SUV 2.0L Turbo AWD", "Unit", FIN),
    ("FG-MPV-ICE-05", "Family MPV 1.5L CVT 7-Seater", "Unit", FIN),
    ("FG-PKP-DSL-06", "Double Cab Pickup 2.4L Diesel 4x2", "Unit", FIN),
    ("FG-SUV-DSL-07", "Ladder-Frame 7-Seat SUV 2.4L Diesel 4x4", "Unit", FIN),
    ("FG-VAN-DSL-08", "Light Commercial Van 2.4L Diesel Manual", "Unit", FIN),
    ("FG-HB-HEV-09", "Hybrid Hatchback 1.5L e-CVT", "Unit", FIN),
    ("FG-SDN-HEV-10", "Hybrid Sedan 1.5L e-CVT", "Unit", FIN),
    ("FG-SUV-HEV-11", "Hybrid SUV 2.0L e-CVT", "Unit", FIN),
    ("FG-MPV-HEV-12", "Hybrid MPV 2.0L e-CVT 7-Seater", "Unit", FIN),
    ("FG-SUV-PHEV-13", "Plug-in Hybrid SUV 2.0L e-CVT", "Unit", FIN),
    ("FG-HB-BEV-14", "Urban Electric Hatchback 40 kWh", "Unit", FIN),
    ("FG-SDN-BEV-15", "Mid-Size Electric Sedan 60 kWh", "Unit", FIN),
    ("FG-SUV-BEV-16", "Compact Electric SUV 60 kWh", "Unit", FIN),
    ("FG-SUV-BEV-17", "Premium Electric SUV Dual Motor 90 kWh", "Unit", FIN),
    ("FG-MPV-BEV-18", "Family Electric MPV 72 kWh", "Unit", FIN),
    ("FG-PKP-BEV-19", "Electric Pickup Dual Motor 90 kWh", "Unit", FIN),
    ("FG-VAN-BEV-20", "Electric Delivery Van 60 kWh", "Unit", FIN),

    # ===================== SUB-PARTS: POWERTRAIN MODULES (L1) =====================
    ("SA-PWR-G12", "Powertrain Module 1.2L Gasoline CVT", "Set", SUB),
    ("SA-PWR-G15", "Powertrain Module 1.5L Gasoline CVT", "Set", SUB),
    ("SA-PWR-G20T", "Powertrain Module 2.0L Turbo Gasoline 8AT AWD", "Set", SUB),
    ("SA-PWR-D24A", "Powertrain Module 2.4L Diesel 6AT", "Set", SUB),
    ("SA-PWR-D24M", "Powertrain Module 2.4L Diesel 6MT", "Set", SUB),
    ("SA-PWR-D24X", "Powertrain Module 2.4L Diesel 6AT 4x4", "Set", SUB),
    ("SA-PWR-HEV15", "Hybrid Powertrain Module 1.5L Atkinson e-CVT", "Set", SUB),
    ("SA-PWR-HEV20", "Hybrid Powertrain Module 2.0L Atkinson e-CVT", "Set", SUB),
    ("SA-PWR-EVS", "EV Powertrain Module Single Motor 150 kW", "Set", SUB),
    ("SA-PWR-EVD", "EV Powertrain Module Dual Motor 350 kW", "Set", SUB),
    # ---- engine assemblies (L2) ----
    ("SA-ENG-G12", "Engine Assembly 1.2L 3-Cyl Gasoline NA", "Unit", SUB),
    ("SA-ENG-G15", "Engine Assembly 1.5L 4-Cyl Gasoline NA", "Unit", SUB),
    ("SA-ENG-G20T", "Engine Assembly 2.0L 4-Cyl Gasoline Turbo GDI", "Unit", SUB),
    ("SA-ENG-D24", "Engine Assembly 2.4L 4-Cyl Common-Rail Diesel", "Unit", SUB),
    ("SA-ENG-H15", "Engine Assembly 1.5L 4-Cyl Atkinson Hybrid", "Unit", SUB),
    ("SA-ENG-H20", "Engine Assembly 2.0L 4-Cyl Atkinson Hybrid GDI", "Unit", SUB),
    # ---- transmission assemblies (L2) ----
    ("SA-TRN-CVT", "Transaxle Assembly CVT", "Unit", SUB),
    ("SA-TRN-AT8", "Transaxle Assembly 8-Speed Automatic", "Unit", SUB),
    ("SA-TRN-AT6", "Transmission Assembly 6-Speed Automatic Heavy-Duty", "Unit", SUB),
    ("SA-TRN-MT6", "Transmission Assembly 6-Speed Manual", "Unit", SUB),
    ("SA-TRN-EVA", "Hybrid Transaxle Assembly e-CVT 1.5L Class", "Unit", SUB),
    ("SA-TRN-EVB", "Hybrid Transaxle Assembly e-CVT 2.0L Class", "Unit", SUB),
    # ---- electric drive units (L2) ----
    ("SA-EMT-HVA", "Hybrid Traction Motor Unit 60 kW", "Unit", SUB),
    ("SA-EMT-HVB", "Hybrid Traction Motor Unit 90 kW", "Unit", SUB),
    ("SA-EMT-EVS", "Electric Drive Unit (e-Axle) 150 kW", "Unit", SUB),
    ("SA-EMT-EVR", "Electric Drive Unit (e-Axle) 200 kW Rear", "Unit", SUB),

    # ===================== SUB-PARTS: ELECTRICAL / BATTERY SYSTEMS =====================
    ("SA-BMD-LFP", "Battery Cell Module LFP 2.0 kWh", "Unit", SUB),
    ("SA-BMD-NMC", "Battery Cell Module NMC 3.0 kWh", "Unit", SUB),
    ("SA-BMD-HEV", "Battery Cell Module Li-ion Hybrid 0.65 kWh", "Unit", SUB),
    ("SA-BAT-HEV", "Battery Pack Hybrid 1.3 kWh", "Unit", SUB),
    ("SA-BAT-PHEV", "Battery Pack Plug-in Hybrid 18 kWh NMC", "Unit", SUB),
    ("SA-BAT-E40", "Battery Pack EV 40 kWh LFP", "Unit", SUB),
    ("SA-BAT-E60", "Battery Pack EV 60 kWh NMC", "Unit", SUB),
    ("SA-BAT-E72", "Battery Pack EV 72 kWh NMC", "Unit", SUB),
    ("SA-BAT-E90", "Battery Pack EV 90 kWh NMC", "Unit", SUB),
    ("SA-CHG-PHEV", "Charging System AC 3.7 kW (Plug-in Hybrid)", "Set", SUB),
    ("SA-CHG-EV", "Charging System AC 11 kW + DC Fast Charge (EV)", "Set", SUB),
    ("SA-ELE-S", "Electrical Module Standard (ICE)", "Set", SUB),
    ("SA-ELE-P", "Electrical Module Premium (ICE with ADAS Level 2)", "Set", SUB),
    ("SA-ELE-HEV", "Electrical Module Hybrid with HV Harness", "Set", SUB),
    ("SA-ELE-EV", "Electrical Module Electric Vehicle with ADAS Level 2", "Set", SUB),
    ("SA-ADAS-L1", "ADAS Sensor Suite Level 1 (AEB + Lane Keep)", "Set", SUB),
    ("SA-ADAS-L2", "ADAS Sensor Suite Level 2 (360 Radar + Driver Monitoring)", "Set", SUB),

    # ===================== SUB-PARTS: BODY & CHASSIS =====================
    ("SA-BIW-HB", "Body-in-White Hatchback (Painted, Glazed)", "Unit", SUB),
    ("SA-BIW-SDN", "Body-in-White Sedan (Painted, Glazed)", "Unit", SUB),
    ("SA-BIW-SUVC", "Body-in-White Compact SUV (Painted, Glazed)", "Unit", SUB),
    ("SA-BIW-SUVM", "Body-in-White Midsize SUV (Painted, Glazed)", "Unit", SUB),
    ("SA-BIW-MPV", "Body-in-White MPV (Painted, Glazed)", "Unit", SUB),
    ("SA-BIW-PKP", "Body-in-White Double Cab Pickup with Cargo Box", "Unit", SUB),
    ("SA-BIW-VAN", "Body-in-White Light Commercial Van with Sliding Door", "Unit", SUB),
    ("SA-CHS-PLTS", "Chassis Module Small Platform", "Set", SUB),
    ("SA-CHS-PLTM", "Chassis Module Mid Platform", "Set", SUB),
    ("SA-CHS-PLTX", "Chassis Module Mid Platform Heavy-Duty Brakes (AWD Ready)", "Set", SUB),
    ("SA-CHS-LDR", "Chassis Module Ladder Frame", "Set", SUB),
    ("SA-CHS-VAN", "Chassis Module Light Commercial Van", "Set", SUB),
    ("SA-SUS-FRT", "Front Suspension Assembly MacPherson Strut", "Set", SUB),
    ("SA-SUS-RTB", "Rear Suspension Assembly Torsion Beam", "Set", SUB),
    ("SA-SUS-RML", "Rear Suspension Assembly Multi-Link", "Set", SUB),
    ("SA-SUS-RLS", "Rear Suspension Assembly Leaf Spring Rigid Axle", "Set", SUB),
    ("SA-BRK-C", "Brake System Assembly Standard", "Set", SUB),
    ("SA-BRK-H", "Brake System Assembly Heavy-Duty", "Set", SUB),
    ("SA-STR-EPS", "Electric Power Steering Assembly", "Set", SUB),
    ("SA-WHL-15", "Wheel & Tyre Set 15-inch", "Set", SUB),
    ("SA-WHL-16", "Wheel & Tyre Set 16-inch", "Set", SUB),
    ("SA-WHL-17", "Wheel & Tyre Set 17-inch", "Set", SUB),
    ("SA-WHL-18", "Wheel & Tyre Set 18-inch", "Set", SUB),
    ("SA-WHL-17LT", "Wheel & Tyre Set 17-inch Light Truck", "Set", SUB),

    # ===================== SUB-PARTS: INTERIOR / COCKPIT =====================
    ("SA-CKP-B", "Cockpit Module Basic (Analog Cluster, Manual A/C)", "Set", SUB),
    ("SA-CKP-M", "Cockpit Module Mid (TFT Cluster, Auto A/C)", "Set", SUB),
    ("SA-CKP-P", "Cockpit Module Premium (12.3-inch Displays, Auto A/C)", "Set", SUB),
    ("SA-CKP-ME", "Cockpit Module Mid for EV (TFT Cluster, Heat-Pump A/C)", "Set", SUB),
    ("SA-CKP-PE", "Cockpit Module Premium for EV (12.3-inch Displays, Heat-Pump A/C)", "Set", SUB),
    ("SA-HVC-MAN", "HVAC Unit Manual", "Set", SUB),
    ("SA-HVC-AUT", "HVAC Unit Automatic Dual Zone", "Set", SUB),
    ("SA-HVC-EV", "HVAC Unit Heat Pump with Electric Compressor", "Set", SUB),
    ("SA-SET-5F", "Seat Set 5-Seater Fabric", "Set", SUB),
    ("SA-SET-5L", "Seat Set 5-Seater Leather Heated", "Set", SUB),
    ("SA-SET-7F", "Seat Set 7-Seater Fabric", "Set", SUB),
    ("SA-SET-7L", "Seat Set 7-Seater Leather Heated", "Set", SUB),
    ("SA-SET-VAN", "Seat Set Commercial Van 3-Seater Cab", "Set", SUB),

    # ===================== PURCHASED: ENGINE & FLUIDS =====================
    ("RM-BLK-G12", "Cylinder Block 1.2L 3-Cyl Aluminum (with Crankshaft & Pistons)", "Pcs", BUY),
    ("RM-HED-G12", "Cylinder Head 1.2L 3-Cyl DOHC 12V", "Pcs", BUY),
    ("RM-BLK-G15", "Cylinder Block 1.5L 4-Cyl Aluminum (with Crankshaft & Pistons)", "Pcs", BUY),
    ("RM-HED-G15", "Cylinder Head 1.5L 4-Cyl DOHC 16V", "Pcs", BUY),
    ("RM-BLK-G20T", "Cylinder Block 2.0L 4-Cyl Turbo Forged Internals", "Pcs", BUY),
    ("RM-HED-G20T", "Cylinder Head 2.0L 4-Cyl Turbo DOHC GDI", "Pcs", BUY),
    ("RM-BLK-D24", "Cylinder Block 2.4L 4-Cyl Diesel Cast Iron (with Crankshaft & Pistons)", "Pcs", BUY),
    ("RM-HED-D24", "Cylinder Head 2.4L 4-Cyl Diesel DOHC 16V", "Pcs", BUY),
    ("RM-BLK-H15", "Cylinder Block 1.5L 4-Cyl Atkinson Cycle", "Pcs", BUY),
    ("RM-HED-H15", "Cylinder Head 1.5L 4-Cyl Atkinson Cycle", "Pcs", BUY),
    ("RM-BLK-H20", "Cylinder Block 2.0L 4-Cyl Atkinson Cycle", "Pcs", BUY),
    ("RM-HED-H20", "Cylinder Head 2.0L 4-Cyl Atkinson Cycle GDI", "Pcs", BUY),
    ("RM-TRB-G20T", "Turbocharger Twin-Scroll 2.0L Gasoline", "Pcs", BUY),
    ("RM-TRB-D24", "Variable Geometry Turbocharger 2.4L Diesel", "Pcs", BUY),
    ("RM-INJ-PFI", "Port Fuel Injector", "Pcs", BUY),
    ("RM-INJ-GDI", "Gasoline Direct Injector High-Pressure", "Pcs", BUY),
    ("RM-INJ-CRD", "Common-Rail Diesel Injector Piezo", "Pcs", BUY),
    ("RM-SPK-IRI", "Iridium Spark Plug", "Pcs", BUY),
    ("RM-GLP-DSL", "Ceramic Glow Plug Diesel", "Pcs", BUY),
    ("RM-CHN-TIM", "Timing Chain Kit with Tensioner & Guides", "Set", BUY),
    ("RM-OWP-SET", "Oil Pump & Water Pump Set", "Set", BUY),
    ("RM-ENM-SET", "Engine & Transmission Mount Set", "Set", BUY),
    ("RM-HPF-CRD", "Common-Rail High-Pressure Fuel Pump", "Pcs", BUY),
    ("RM-EGR-DSL", "EGR Valve & Cooler Assembly Diesel", "Pcs", BUY),
    ("RM-ECU-ENG-G", "Engine Control Module Gasoline", "Pcs", BUY),
    ("RM-ECU-ENG-D", "Engine Control Module Diesel", "Pcs", BUY),
    ("RM-EOL-5W30", "Engine Oil SAE 5W-30 Fully Synthetic", "L", BUY),

    # ===================== PURCHASED: TRANSMISSION, DRIVELINE & e-DRIVE =====================
    ("RM-TAX-CVT", "CVT Transaxle Case & Variator Set", "Set", BUY),
    ("RM-TQC-CVT", "Torque Converter for CVT", "Pcs", BUY),
    ("RM-TAX-AT8", "8-Speed Automatic Transaxle Case & Gear Train", "Set", BUY),
    ("RM-TQC-AT8", "Torque Converter for 8AT", "Pcs", BUY),
    ("RM-TAX-AT6", "6-Speed Heavy-Duty Automatic Case & Gear Train", "Set", BUY),
    ("RM-TQC-AT6", "Torque Converter for 6AT Heavy-Duty", "Pcs", BUY),
    ("RM-TAX-MT6", "6-Speed Manual Gearbox Case & Gear Train", "Set", BUY),
    ("RM-CLU-MT6", "Clutch Kit with Dual-Mass Flywheel", "Set", BUY),
    ("RM-TAX-EVA", "e-CVT Power-Split Transaxle 1.5L Class", "Set", BUY),
    ("RM-TAX-EVB", "e-CVT Power-Split Transaxle 2.0L Class", "Set", BUY),
    ("RM-ATF-FLD", "Transmission Fluid ATF / CVT / Gear Oil", "L", BUY),
    ("RM-TFC-AWD", "Transfer Case & Driveshaft Set 4WD / AWD", "Set", BUY),
    ("RM-MTR-60", "Traction Motor PMSM 60 kW (Stator & Rotor)", "Pcs", BUY),
    ("RM-MTR-90", "Traction Motor PMSM 90 kW (Stator & Rotor)", "Pcs", BUY),
    ("RM-MTR-150", "Traction Motor PMSM 150 kW (Stator & Rotor)", "Pcs", BUY),
    ("RM-MTR-200", "Traction Motor PMSM 200 kW (Stator & Rotor)", "Pcs", BUY),
    ("RM-INV-HYB", "Hybrid Inverter / Power Control Unit", "Pcs", BUY),
    ("RM-INV-EV", "Traction Inverter SiC 400V", "Pcs", BUY),
    ("RM-RDG-S", "Single-Speed Reduction Gear Housing & Gear Set Small", "Set", BUY),
    ("RM-RDG-L", "Single-Speed Reduction Gear Housing & Gear Set Large", "Set", BUY),

    # ===================== PURCHASED: POWERTRAIN-LEVEL AUXILIARIES =====================
    ("RM-ECU-HCU", "Hybrid Control Unit", "Pcs", BUY),
    ("RM-ECU-VCU", "Vehicle Control Unit (EV)", "Pcs", BUY),
    ("RM-EXH-GAS", "Exhaust System with Three-Way Catalytic Converter & GPF", "Set", BUY),
    ("RM-EXH-DSL", "Exhaust System with DOC, DPF & SCR", "Set", BUY),
    ("RM-RAD-S", "Radiator & Cooling Fan Assembly Small", "Pcs", BUY),
    ("RM-RAD-L", "Radiator & Cooling Fan Assembly Large", "Pcs", BUY),
    ("RM-FTK-S", "Fuel Tank 45 L with Fuel Pump Module", "Pcs", BUY),
    ("RM-FTK-L", "Fuel Tank 70 L with Fuel Pump Module", "Pcs", BUY),
    ("RM-DEF-TNK", "AdBlue / DEF Tank & Dosing Pump Module", "Set", BUY),
    ("RM-TMS-EV", "EV Thermal Management Coolant Pump & Valve Module", "Set", BUY),

    # ===================== PURCHASED: BATTERY SYSTEMS & CHARGING =====================
    ("RM-CEL-LFP", "LFP Prismatic Cell 3.2V 105Ah", "Pcs", BUY),
    ("RM-CEL-NMC", "NMC Prismatic Cell 3.65V 70Ah", "Pcs", BUY),
    ("RM-CEL-HEV", "Li-ion Cylindrical Cell 21700 3.6V 5Ah", "Pcs", BUY),
    ("RM-BUS-MOD", "Module Busbar & Connector Set", "Set", BUY),
    ("RM-CSC-MOD", "Cell Supervision Circuit Board", "Pcs", BUY),
    ("RM-TIM-PAD", "Thermal Interface Pad & Insulation Set", "Set", BUY),
    ("RM-BMS-HEV", "Battery Management System Master Hybrid", "Pcs", BUY),
    ("RM-BMS-EV", "Battery Management System Master EV", "Pcs", BUY),
    ("RM-ENC-HEV", "Battery Pack Enclosure Hybrid", "Pcs", BUY),
    ("RM-ENC-PHEV", "Battery Pack Enclosure Plug-in Hybrid", "Pcs", BUY),
    ("RM-ENC-EVS", "Battery Pack Enclosure EV Standard (Aluminum Tray & Cover)", "Pcs", BUY),
    ("RM-ENC-EVL", "Battery Pack Enclosure EV Long (Aluminum Tray & Cover)", "Pcs", BUY),
    ("RM-CLP-EV", "Liquid Cooling Plate for Battery Modules", "Pcs", BUY),
    ("RM-HVJ-EV", "High-Voltage Junction Box with Contactors & Fuses", "Pcs", BUY),
    ("RM-MSD-HV", "Manual Service Disconnect", "Pcs", BUY),
    ("RM-OBC-37", "On-Board Charger 3.7 kW", "Pcs", BUY),
    ("RM-OBC-110", "On-Board Charger 11 kW", "Pcs", BUY),
    ("RM-INL-T2", "Charging Inlet AC Type 2", "Pcs", BUY),
    ("RM-INL-CCS2", "Charging Inlet Combo CCS2 (AC + DC)", "Pcs", BUY),
    ("RM-CBL-EVSE", "Portable Charging Cable Mode 2 / Mode 3", "Pcs", BUY),

    # ===================== PURCHASED: BODY, PAINT & CLOSURES =====================
    ("RM-BSH-HB", "Stamped Body Shell Kit Hatchback", "Set", BUY),
    ("RM-BSH-SDN", "Stamped Body Shell Kit Sedan", "Set", BUY),
    ("RM-BSH-SUVC", "Stamped Body Shell Kit Compact SUV", "Set", BUY),
    ("RM-BSH-SUVM", "Stamped Body Shell Kit Midsize SUV", "Set", BUY),
    ("RM-BSH-MPV", "Stamped Body Shell Kit MPV", "Set", BUY),
    ("RM-BSH-PKP", "Stamped Body Shell Kit Double Cab Pickup", "Set", BUY),
    ("RM-BSH-VAN", "Stamped Body Shell Kit Light Commercial Van", "Set", BUY),
    ("RM-DRS-C", "Door & Closure Set Compact (4 Doors, Hood, Tailgate/Trunk)", "Set", BUY),
    ("RM-DRS-L", "Door & Closure Set Large (4 Doors, Hood, Tailgate)", "Set", BUY),
    ("RM-BMP-S", "Front & Rear Bumper Set Small", "Set", BUY),
    ("RM-BMP-L", "Front & Rear Bumper Set Large", "Set", BUY),
    ("RM-HLP-LED", "LED Headlamp Pair", "Set", BUY),
    ("RM-TLP-LED", "LED Tail Lamp Pair", "Set", BUY),
    ("RM-GLZ-S", "Glazing Set Small (Windshield, Side & Rear Glass)", "Set", BUY),
    ("RM-GLZ-L", "Glazing Set Large (Windshield, Side & Rear Glass)", "Set", BUY),
    ("RM-MIR-STD", "Side Mirror Pair Heated Power-Folding", "Set", BUY),
    ("RM-PNT-BSC", "Waterborne Basecoat Paint", "L", BUY),
    ("RM-PNT-CLR", "2K Clearcoat Paint", "L", BUY),
    ("RM-CGB-PKP", "Pickup Cargo Box Assembly", "Pcs", BUY),
    ("RM-SLD-VAN", "Sliding Door Assembly Van", "Pcs", BUY),

    # ===================== PURCHASED: SUSPENSION, BRAKES, STEERING, FRAMES =====================
    ("RM-STR-FRT", "Front Strut Assembly with Coil Spring", "Pcs", BUY),
    ("RM-LCA-FRT", "Front Lower Control Arm", "Pcs", BUY),
    ("RM-KNK-FRT", "Front Steering Knuckle with Wheel Bearing", "Pcs", BUY),
    ("RM-SUB-FRT", "Front Subframe Cradle", "Pcs", BUY),
    ("RM-TBA-RR", "Rear Torsion Beam Axle", "Pcs", BUY),
    ("RM-MLA-RR", "Rear Multi-Link Axle with Subframe", "Pcs", BUY),
    ("RM-RAX-RR", "Rear Rigid Axle Housing with Differential", "Pcs", BUY),
    ("RM-LSP-RR", "Rear Leaf Spring Pack", "Pcs", BUY),
    ("RM-SPD-RR", "Rear Coil Spring & Damper Set", "Set", BUY),
    ("RM-DMP-RR", "Rear Shock Absorber", "Pcs", BUY),
    ("RM-BFR-C", "Front Brake Disc & Caliper Set Standard", "Set", BUY),
    ("RM-BRR-C", "Rear Brake Disc & Caliper Set Standard", "Set", BUY),
    ("RM-BFR-H", "Front Brake Disc & Caliper Set Heavy-Duty", "Set", BUY),
    ("RM-BRR-H", "Rear Brake Disc & Caliper Set Heavy-Duty", "Set", BUY),
    ("RM-ABS-ESC", "ABS / ESC Hydraulic Control Unit", "Pcs", BUY),
    ("RM-ABS-WSS", "ABS Wheel Speed Sensor", "Pcs", BUY),
    ("RM-BMC-STD", "Brake Master Cylinder & Booster", "Set", BUY),
    ("RM-EPB-ACT", "Electric Parking Brake Actuator", "Pcs", BUY),
    ("RM-BRF-DOT4", "Brake Fluid DOT 4", "L", BUY),
    ("RM-RCK-EPS", "Steering Rack with Pinion", "Pcs", BUY),
    ("RM-EPM-EPS", "EPS Assist Motor & Controller", "Pcs", BUY),
    ("RM-STC-STD", "Steering Column Collapsible", "Pcs", BUY),
    ("RM-LDR-FRM", "Ladder Frame Chassis Rail Assembly", "Pcs", BUY),
    ("RM-UBF-VAN", "Reinforced Underbody Frame Van", "Pcs", BUY),

    # ===================== PURCHASED: WHEELS & TYRES =====================
    ("RM-WHL-ALU-15", "Alloy Wheel 15-inch 4x100", "Pcs", BUY),
    ("RM-WHL-ALU-16", "Alloy Wheel 16-inch 5x114.3", "Pcs", BUY),
    ("RM-WHL-ALU-17", "Alloy Wheel 17-inch 5x114.3", "Pcs", BUY),
    ("RM-WHL-ALU-18", "Alloy Wheel 18-inch 5x114.3", "Pcs", BUY),
    ("RM-TYR-15", "Tyre 175/65 R15", "Pcs", BUY),
    ("RM-TYR-16", "Tyre 205/55 R16", "Pcs", BUY),
    ("RM-TYR-17", "Tyre 215/55 R17", "Pcs", BUY),
    ("RM-TYR-18", "Tyre 235/55 R18", "Pcs", BUY),
    ("RM-TYR-17LT", "Tyre 265/65 R17 Light Truck", "Pcs", BUY),
    ("RM-WHL-HW", "Wheel Hardware Kit (Lug Nuts, Valves, TPMS Sensors)", "Set", BUY),

    # ===================== PURCHASED: COCKPIT, HVAC & INFOTAINMENT =====================
    ("RM-DSH-B", "Instrument Panel & Console Basic", "Set", BUY),
    ("RM-DSH-M", "Instrument Panel & Console Mid", "Set", BUY),
    ("RM-DSH-P", "Instrument Panel & Console Premium Soft-Touch", "Set", BUY),
    ("RM-CLS-ANA", "Instrument Cluster Analog with 3.5-inch Display", "Pcs", BUY),
    ("RM-CLS-TFT", "Digital Instrument Cluster 7-inch TFT", "Pcs", BUY),
    ("RM-CLS-TFT12", "Digital Instrument Cluster 12.3-inch TFT", "Pcs", BUY),
    ("RM-HDU-7", "Head Unit 7-inch Touchscreen", "Pcs", BUY),
    ("RM-HDU-9", "Head Unit 9-inch Touchscreen with Wireless Projection", "Pcs", BUY),
    ("RM-HDU-12", "Head Unit 12.3-inch Touchscreen with Navigation", "Pcs", BUY),
    ("RM-STW-STD", "Steering Wheel with Driver Airbag Urethane", "Pcs", BUY),
    ("RM-STW-PRM", "Steering Wheel with Driver Airbag Leather Multifunction", "Pcs", BUY),
    ("RM-ARB-PAS", "Passenger Airbag Module", "Pcs", BUY),
    ("RM-ARB-KNEE", "Driver Knee Airbag Module", "Pcs", BUY),
    ("RM-PED-SET", "Pedal Assembly with Position Sensors", "Set", BUY),
    ("RM-AUD-6", "Audio Speaker Set 6-Speaker", "Set", BUY),
    ("RM-AUD-8", "Premium Audio Set 8-Speaker with Amplifier", "Set", BUY),
    ("RM-TRM-SET", "Interior Trim Set (Headliner, Carpet, Door Trims)", "Set", BUY),
    ("RM-HVC-CSE-M", "HVAC Case Single Zone Manual", "Pcs", BUY),
    ("RM-HVC-CSE-A", "HVAC Case Dual Zone Automatic", "Pcs", BUY),
    ("RM-BLW-MTR", "HVAC Blower Motor", "Pcs", BUY),
    ("RM-EVP-CORE", "A/C Evaporator Core", "Pcs", BUY),
    ("RM-CND-AC", "A/C Condenser", "Pcs", BUY),
    ("RM-ACC-MECH", "A/C Compressor Belt-Driven", "Pcs", BUY),
    ("RM-ACC-ELE", "A/C Compressor Electric Scroll 400V", "Pcs", BUY),
    ("RM-HVC-CTL", "Automatic Climate Controller", "Pcs", BUY),
    ("RM-PTC-HTR", "High-Voltage PTC Cabin Heater", "Pcs", BUY),

    # ===================== PURCHASED: SEATING =====================
    ("RM-SFR-FM", "Front Seat Frame Pair Manual Adjust", "Set", BUY),
    ("RM-SFR-FP", "Front Seat Frame Pair 8-Way Power", "Set", BUY),
    ("RM-SFR-R", "Rear Bench Seat Frame 60/40", "Pcs", BUY),
    ("RM-SFR-3R", "Third Row Seat Frame Folding", "Pcs", BUY),
    ("RM-SFR-VAN", "Van Cab Bench Seat Frame 3-Seat", "Pcs", BUY),
    ("RM-FOM-SEAT", "Seat Foam Cushion & Backrest Set (per Row)", "Set", BUY),
    ("RM-COV-FAB", "Seat Cover Set Fabric (per Row)", "Set", BUY),
    ("RM-COV-LTH", "Seat Cover Set Genuine Leather (per Row)", "Set", BUY),
    ("RM-COV-VNL-VAN", "Seat Cover Set Heavy-Duty Vinyl Van", "Set", BUY),
    ("RM-SHT-HEAT", "Seat Heater Pad Pair", "Set", BUY),
    ("RM-SBT-SET", "Seatbelt Set with Pretensioners", "Set", BUY),

    # ===================== PURCHASED: ELECTRICAL & ELECTRONICS =====================
    ("RM-HRN-BDY-S", "Body Wiring Harness Standard", "Set", BUY),
    ("RM-HRN-BDY-P", "Body Wiring Harness Premium", "Set", BUY),
    ("RM-HRN-DOR", "Door Wiring Harness Set", "Set", BUY),
    ("RM-HRN-ENG", "Engine Wiring Harness", "Set", BUY),
    ("RM-HRN-HV-HEV", "High-Voltage Cable Harness Hybrid", "Set", BUY),
    ("RM-HRN-HV-EV", "High-Voltage Cable Harness EV", "Set", BUY),
    ("RM-BAT-12V-PB", "12V Lead-Acid Battery 45Ah", "Pcs", BUY),
    ("RM-BAT-12V-LI", "12V Lithium-Ion Auxiliary Battery", "Pcs", BUY),
    ("RM-ALT-STD", "Alternator 120A", "Pcs", BUY),
    ("RM-STM-STD", "Starter Motor", "Pcs", BUY),
    ("RM-BCM-STD", "Body Control Module", "Pcs", BUY),
    ("RM-FSB-SET", "Fuse & Relay Box Set", "Set", BUY),
    ("RM-SNS-PRK", "Ultrasonic Parking Sensor", "Pcs", BUY),
    ("RM-CAM-RVW", "Rear View Camera", "Pcs", BUY),
    ("RM-CAM-360", "Surround View Camera System 4-Camera", "Set", BUY),
    ("RM-KEY-IMM", "Remote Key Fob with Immobilizer", "Pcs", BUY),
    ("RM-KEY-SMT", "Smart Key Fob with Push-Button Start Module", "Pcs", BUY),
    ("RM-TCU-TEL", "Telematics Control Unit with eSIM", "Pcs", BUY),
    ("RM-DCDC-HV", "DC-DC Converter HV to 12V", "Pcs", BUY),
    ("RM-AVAS", "Acoustic Vehicle Alerting System Speaker", "Pcs", BUY),
    ("RM-CAM-FRT", "ADAS Front Camera Module", "Pcs", BUY),
    ("RM-RDR-FRT", "ADAS Front Radar 77 GHz", "Pcs", BUY),
    ("RM-RDR-CRN", "ADAS Corner Radar 77 GHz", "Pcs", BUY),
    ("RM-DMS-CAM", "Driver Monitoring Camera IR", "Pcs", BUY),
    ("RM-ADC-L1", "ADAS Controller Level 1", "Pcs", BUY),
    ("RM-ADC-L2", "ADAS Domain Controller Level 2", "Pcs", BUY),

    # ===================== SOKRATESCAR (21st vehicle; fully dedicated BOM, sourced only from PT Fandi & PT Chris) =====================
    ("FG-SDN-SKR-21", "SokratesCar", "Unit", FIN),
    ("SA-SKR-PWR", "SokratesCar Powertrain Module 1.5L Gasoline CVT", "Set", SUB),
    ("SA-SKR-ENG", "SokratesCar Engine Assembly 1.5L 4-Cyl", "Unit", SUB),
    ("SA-SKR-BODY", "SokratesCar Body & Chassis Module", "Set", SUB),
    ("SA-SKR-CHS", "SokratesCar Chassis Assembly (Suspension, Brake, Steering, Wheels)", "Set", SUB),
    ("SA-SKR-INT", "SokratesCar Interior / Cockpit Module", "Set", SUB),
    ("SA-SKR-ELE", "SokratesCar Electrical Module", "Set", SUB),
    ("RM-SKR-TRN", "SokratesCar CVT Transaxle with Torque Converter", "Set", BUY),
    ("RM-SKR-ECU", "SokratesCar Engine Control Module", "Pcs", BUY),
    ("RM-SKR-EXH", "SokratesCar Exhaust System with Catalytic Converter", "Set", BUY),
    ("RM-SKR-RAD", "SokratesCar Radiator & Cooling Fan", "Pcs", BUY),
    ("RM-SKR-FTK", "SokratesCar Fuel Tank 45 L with Pump Module", "Pcs", BUY),
    ("RM-SKR-BLK", "SokratesCar Cylinder Block 1.5L with Crankshaft & Pistons", "Pcs", BUY),
    ("RM-SKR-HED", "SokratesCar Cylinder Head 1.5L DOHC 16V", "Pcs", BUY),
    ("RM-SKR-INJ", "SokratesCar Port Fuel Injector", "Pcs", BUY),
    ("RM-SKR-SPK", "SokratesCar Iridium Spark Plug", "Pcs", BUY),
    ("RM-SKR-OIL", "SokratesCar Engine Oil SAE 5W-30", "L", BUY),
    ("RM-SKR-BSH", "SokratesCar Stamped Body Shell Kit", "Set", BUY),
    ("RM-SKR-DRS", "SokratesCar Door & Closure Set", "Set", BUY),
    ("RM-SKR-BMP", "SokratesCar Front & Rear Bumper Set", "Set", BUY),
    ("RM-SKR-GLZ", "SokratesCar Glazing Set (Windshield, Side & Rear Glass)", "Set", BUY),
    ("RM-SKR-PNT", "SokratesCar Paint System (Basecoat & Clearcoat)", "L", BUY),
    ("RM-SKR-SUSF", "SokratesCar Front Suspension Set", "Set", BUY),
    ("RM-SKR-SUSR", "SokratesCar Rear Suspension Set", "Set", BUY),
    ("RM-SKR-BRK", "SokratesCar Brake System Set with ABS", "Set", BUY),
    ("RM-SKR-STR", "SokratesCar Electric Power Steering Set", "Set", BUY),
    ("RM-SKR-WHL", "SokratesCar Alloy Wheel & Tyre Set 16-inch", "Set", BUY),
    ("RM-SKR-DSH", "SokratesCar Instrument Panel & Console", "Set", BUY),
    ("RM-SKR-SEAT", "SokratesCar Seat Set 5-Seater Fabric", "Set", BUY),
    ("RM-SKR-HVC", "SokratesCar HVAC Unit Automatic", "Set", BUY),
    ("RM-SKR-HDU", "SokratesCar Head Unit 9-inch Touchscreen", "Pcs", BUY),
    ("RM-SKR-TRM", "SokratesCar Interior Trim Set", "Set", BUY),
    ("RM-SKR-HRN", "SokratesCar Complete Wiring Harness Set", "Set", BUY),
    ("RM-SKR-BAT12", "SokratesCar 12V Battery 45Ah", "Pcs", BUY),
    ("RM-SKR-BCM", "SokratesCar Body Control Module", "Pcs", BUY),
    ("RM-SKR-ALT", "SokratesCar Alternator 120A", "Pcs", BUY),
    ("RM-SKR-STM", "SokratesCar Starter Motor", "Pcs", BUY),
    ("RM-SKR-LGT", "SokratesCar LED Head & Tail Lamp Set", "Set", BUY),
]

# Finished vehicle selling price (Rp) and specification
FINISHED = {
    "FG-HB-ICE-01": (218_000_000, "Powertrain: ICE gasoline 1.2L 3-cyl NA, 82 hp, CVT, FWD; Segment: A/B city hatchback; Seats: 5; Battery: 12V lead-acid only; Range: approx. 650 km (45 L tank)"),
    "FG-SDN-ICE-02": (289_000_000, "Powertrain: ICE gasoline 1.5L 4-cyl NA, 107 hp, CVT, FWD; Segment: C compact sedan; Seats: 5; Battery: 12V lead-acid only; Range: approx. 720 km (45 L tank)"),
    "FG-SUV-ICE-03": (359_000_000, "Powertrain: ICE gasoline 1.5L 4-cyl NA, 107 hp, CVT, FWD; Segment: B-SUV compact crossover; Seats: 5; Battery: 12V lead-acid only; Range: approx. 650 km (45 L tank)"),
    "FG-SUV-ICE-04": (598_000_000, "Powertrain: ICE gasoline 2.0L turbo GDI, 235 hp, 8AT, AWD; Segment: D-SUV midsize; Seats: 5 leather heated; Battery: 12V lead-acid only; Range: approx. 600 km (45 L tank)"),
    "FG-MPV-ICE-05": (279_000_000, "Powertrain: ICE gasoline 1.5L 4-cyl NA, 107 hp, CVT, FWD; Segment: family MPV; Seats: 7; Battery: 12V lead-acid only; Range: approx. 620 km (45 L tank)"),
    "FG-PKP-DSL-06": (389_000_000, "Powertrain: ICE diesel 2.4L common-rail turbo, 150 hp, 6AT, 4x2; Segment: 1-ton double cab pickup; Seats: 5; Battery: 12V lead-acid only; Range: approx. 900 km (70 L tank)"),
    "FG-SUV-DSL-07": (585_000_000, "Powertrain: ICE diesel 2.4L common-rail turbo, 150 hp, 6AT, 4x4 with transfer case; Segment: ladder-frame SUV; Seats: 7 leather; Battery: 12V lead-acid only; Range: approx. 850 km (70 L tank)"),
    "FG-VAN-DSL-08": (349_000_000, "Powertrain: ICE diesel 2.4L common-rail turbo, 150 hp, 6MT, RWD; Segment: light commercial van; Seats: 3 (cab); Battery: 12V lead-acid only; Range: approx. 850 km (70 L tank)"),
    "FG-HB-HEV-09": (349_000_000, "Powertrain: full hybrid 1.5L Atkinson + 60 kW motor, e-CVT, FWD; Segment: B hatchback; Seats: 5; Battery: 1.3 kWh Li-ion; Range: approx. 900 km combined (45 L tank)"),
    "FG-SDN-HEV-10": (459_000_000, "Powertrain: full hybrid 1.5L Atkinson + 60 kW motor, e-CVT, FWD; Segment: C sedan; Seats: 5 leather; Battery: 1.3 kWh Li-ion; Range: approx. 950 km combined (45 L tank)"),
    "FG-SUV-HEV-11": (629_000_000, "Powertrain: full hybrid 2.0L Atkinson + 90 kW motor, e-CVT, AWD-ready platform; Segment: D-SUV midsize; Seats: 5 leather; Battery: 1.3 kWh Li-ion; Range: approx. 850 km combined (45 L tank)"),
    "FG-MPV-HEV-12": (539_000_000, "Powertrain: full hybrid 2.0L Atkinson + 90 kW motor, e-CVT, FWD; Segment: premium family MPV; Seats: 7 leather; Battery: 1.3 kWh Li-ion; Range: approx. 850 km combined (45 L tank)"),
    "FG-SUV-PHEV-13": (889_000_000, "Powertrain: plug-in hybrid 2.0L Atkinson + 90 kW motor, e-CVT; Segment: D-SUV midsize; Seats: 5 leather; Battery: 18 kWh NMC, AC 3.7 kW; Range: 70 km EV + 800 km combined"),
    "FG-HB-BEV-14": (375_000_000, "Powertrain: BEV single motor 150 kW FWD; Segment: B urban hatchback; Seats: 5; Battery: 40 kWh LFP, AC 11 kW / DC fast charge; Range: approx. 300 km (WLTP)"),
    "FG-SDN-BEV-15": (569_000_000, "Powertrain: BEV single motor 150 kW RWD; Segment: D mid-size sedan; Seats: 5 leather; Battery: 60 kWh NMC, AC 11 kW / DC fast charge; Range: approx. 480 km (WLTP)"),
    "FG-SUV-BEV-16": (619_000_000, "Powertrain: BEV single motor 150 kW RWD; Segment: C-SUV compact crossover; Seats: 5 leather; Battery: 60 kWh NMC, AC 11 kW / DC fast charge; Range: approx. 420 km (WLTP)"),
    "FG-SUV-BEV-17": (1_249_000_000, "Powertrain: BEV dual motor 350 kW AWD; Segment: premium D-SUV; Seats: 5 leather; Battery: 90 kWh NMC, AC 11 kW / DC fast charge; Range: approx. 560 km (WLTP)"),
    "FG-MPV-BEV-18": (789_000_000, "Powertrain: BEV single motor 150 kW FWD; Segment: premium family MPV; Seats: 7 leather; Battery: 72 kWh NMC, AC 11 kW / DC fast charge; Range: approx. 430 km (WLTP)"),
    "FG-PKP-BEV-19": (979_000_000, "Powertrain: BEV dual motor 350 kW AWD; Segment: 1-ton double cab pickup; Seats: 5 leather; Battery: 90 kWh NMC, AC 11 kW / DC fast charge; Range: approx. 450 km (WLTP)"),
    "FG-SDN-SKR-21": (299_000_000, "Powertrain: ICE gasoline 1.5L 4-cyl NA, 107 hp, CVT, FWD; Segment: C compact sedan; Seats: 5 fabric; Battery: 12V lead-acid only; Range: approx. 700 km (45 L tank); Note: test product, all raw materials sourced only from PT Fandi and PT Chris"),
    "FG-VAN-BEV-20": (559_000_000, "Powertrain: BEV single motor 150 kW; Segment: light commercial delivery van; Seats: 3 (cab); Battery: 60 kWh NMC, AC 11 kW / DC fast charge; Range: approx. 300 km (WLTP, laden)"),
}

# parent, child, qty_per_parent
BOM = [
    # ===== LEVEL 0 -> LEVEL 1: finished vehicle -> modules =====
    # Order: powertrain, body-in-white, chassis, cockpit, seats, electrical, wheels, [battery], [charging]
    ("FG-HB-ICE-01", "SA-PWR-G12", 1), ("FG-HB-ICE-01", "SA-BIW-HB", 1), ("FG-HB-ICE-01", "SA-CHS-PLTS", 1),
    ("FG-HB-ICE-01", "SA-CKP-B", 1), ("FG-HB-ICE-01", "SA-SET-5F", 1), ("FG-HB-ICE-01", "SA-ELE-S", 1),
    ("FG-HB-ICE-01", "SA-WHL-15", 1),

    ("FG-SDN-ICE-02", "SA-PWR-G15", 1), ("FG-SDN-ICE-02", "SA-BIW-SDN", 1), ("FG-SDN-ICE-02", "SA-CHS-PLTM", 1),
    ("FG-SDN-ICE-02", "SA-CKP-M", 1), ("FG-SDN-ICE-02", "SA-SET-5F", 1), ("FG-SDN-ICE-02", "SA-ELE-S", 1),
    ("FG-SDN-ICE-02", "SA-WHL-16", 1),

    ("FG-SUV-ICE-03", "SA-PWR-G15", 1), ("FG-SUV-ICE-03", "SA-BIW-SUVC", 1), ("FG-SUV-ICE-03", "SA-CHS-PLTM", 1),
    ("FG-SUV-ICE-03", "SA-CKP-M", 1), ("FG-SUV-ICE-03", "SA-SET-5F", 1), ("FG-SUV-ICE-03", "SA-ELE-S", 1),
    ("FG-SUV-ICE-03", "SA-WHL-16", 1),

    ("FG-SUV-ICE-04", "SA-PWR-G20T", 1), ("FG-SUV-ICE-04", "SA-BIW-SUVM", 1), ("FG-SUV-ICE-04", "SA-CHS-PLTX", 1),
    ("FG-SUV-ICE-04", "SA-CKP-P", 1), ("FG-SUV-ICE-04", "SA-SET-5L", 1), ("FG-SUV-ICE-04", "SA-ELE-P", 1),
    ("FG-SUV-ICE-04", "SA-WHL-18", 1),

    ("FG-MPV-ICE-05", "SA-PWR-G15", 1), ("FG-MPV-ICE-05", "SA-BIW-MPV", 1), ("FG-MPV-ICE-05", "SA-CHS-PLTM", 1),
    ("FG-MPV-ICE-05", "SA-CKP-M", 1), ("FG-MPV-ICE-05", "SA-SET-7F", 1), ("FG-MPV-ICE-05", "SA-ELE-S", 1),
    ("FG-MPV-ICE-05", "SA-WHL-16", 1),

    ("FG-PKP-DSL-06", "SA-PWR-D24A", 1), ("FG-PKP-DSL-06", "SA-BIW-PKP", 1), ("FG-PKP-DSL-06", "SA-CHS-LDR", 1),
    ("FG-PKP-DSL-06", "SA-CKP-B", 1), ("FG-PKP-DSL-06", "SA-SET-5F", 1), ("FG-PKP-DSL-06", "SA-ELE-S", 1),
    ("FG-PKP-DSL-06", "SA-WHL-17LT", 1),

    ("FG-SUV-DSL-07", "SA-PWR-D24X", 1), ("FG-SUV-DSL-07", "SA-BIW-SUVM", 1), ("FG-SUV-DSL-07", "SA-CHS-LDR", 1),
    ("FG-SUV-DSL-07", "SA-CKP-P", 1), ("FG-SUV-DSL-07", "SA-SET-7L", 1), ("FG-SUV-DSL-07", "SA-ELE-P", 1),
    ("FG-SUV-DSL-07", "SA-WHL-17LT", 1),

    ("FG-VAN-DSL-08", "SA-PWR-D24M", 1), ("FG-VAN-DSL-08", "SA-BIW-VAN", 1), ("FG-VAN-DSL-08", "SA-CHS-VAN", 1),
    ("FG-VAN-DSL-08", "SA-CKP-B", 1), ("FG-VAN-DSL-08", "SA-SET-VAN", 1), ("FG-VAN-DSL-08", "SA-ELE-S", 1),
    ("FG-VAN-DSL-08", "SA-WHL-17LT", 1),

    ("FG-HB-HEV-09", "SA-PWR-HEV15", 1), ("FG-HB-HEV-09", "SA-BIW-HB", 1), ("FG-HB-HEV-09", "SA-CHS-PLTS", 1),
    ("FG-HB-HEV-09", "SA-CKP-M", 1), ("FG-HB-HEV-09", "SA-SET-5F", 1), ("FG-HB-HEV-09", "SA-ELE-HEV", 1),
    ("FG-HB-HEV-09", "SA-WHL-16", 1), ("FG-HB-HEV-09", "SA-BAT-HEV", 1),

    ("FG-SDN-HEV-10", "SA-PWR-HEV15", 1), ("FG-SDN-HEV-10", "SA-BIW-SDN", 1), ("FG-SDN-HEV-10", "SA-CHS-PLTM", 1),
    ("FG-SDN-HEV-10", "SA-CKP-M", 1), ("FG-SDN-HEV-10", "SA-SET-5L", 1), ("FG-SDN-HEV-10", "SA-ELE-HEV", 1),
    ("FG-SDN-HEV-10", "SA-WHL-16", 1), ("FG-SDN-HEV-10", "SA-BAT-HEV", 1),

    ("FG-SUV-HEV-11", "SA-PWR-HEV20", 1), ("FG-SUV-HEV-11", "SA-BIW-SUVM", 1), ("FG-SUV-HEV-11", "SA-CHS-PLTX", 1),
    ("FG-SUV-HEV-11", "SA-CKP-P", 1), ("FG-SUV-HEV-11", "SA-SET-5L", 1), ("FG-SUV-HEV-11", "SA-ELE-HEV", 1),
    ("FG-SUV-HEV-11", "SA-WHL-18", 1), ("FG-SUV-HEV-11", "SA-BAT-HEV", 1),

    ("FG-MPV-HEV-12", "SA-PWR-HEV20", 1), ("FG-MPV-HEV-12", "SA-BIW-MPV", 1), ("FG-MPV-HEV-12", "SA-CHS-PLTM", 1),
    ("FG-MPV-HEV-12", "SA-CKP-M", 1), ("FG-MPV-HEV-12", "SA-SET-7L", 1), ("FG-MPV-HEV-12", "SA-ELE-HEV", 1),
    ("FG-MPV-HEV-12", "SA-WHL-17", 1), ("FG-MPV-HEV-12", "SA-BAT-HEV", 1),

    ("FG-SUV-PHEV-13", "SA-PWR-HEV20", 1), ("FG-SUV-PHEV-13", "SA-BIW-SUVM", 1), ("FG-SUV-PHEV-13", "SA-CHS-PLTX", 1),
    ("FG-SUV-PHEV-13", "SA-CKP-P", 1), ("FG-SUV-PHEV-13", "SA-SET-5L", 1), ("FG-SUV-PHEV-13", "SA-ELE-HEV", 1),
    ("FG-SUV-PHEV-13", "SA-WHL-18", 1), ("FG-SUV-PHEV-13", "SA-BAT-PHEV", 1), ("FG-SUV-PHEV-13", "SA-CHG-PHEV", 1),

    ("FG-HB-BEV-14", "SA-PWR-EVS", 1), ("FG-HB-BEV-14", "SA-BIW-HB", 1), ("FG-HB-BEV-14", "SA-CHS-PLTS", 1),
    ("FG-HB-BEV-14", "SA-CKP-ME", 1), ("FG-HB-BEV-14", "SA-SET-5F", 1), ("FG-HB-BEV-14", "SA-ELE-EV", 1),
    ("FG-HB-BEV-14", "SA-WHL-16", 1), ("FG-HB-BEV-14", "SA-BAT-E40", 1), ("FG-HB-BEV-14", "SA-CHG-EV", 1),

    ("FG-SDN-BEV-15", "SA-PWR-EVS", 1), ("FG-SDN-BEV-15", "SA-BIW-SDN", 1), ("FG-SDN-BEV-15", "SA-CHS-PLTM", 1),
    ("FG-SDN-BEV-15", "SA-CKP-ME", 1), ("FG-SDN-BEV-15", "SA-SET-5L", 1), ("FG-SDN-BEV-15", "SA-ELE-EV", 1),
    ("FG-SDN-BEV-15", "SA-WHL-17", 1), ("FG-SDN-BEV-15", "SA-BAT-E60", 1), ("FG-SDN-BEV-15", "SA-CHG-EV", 1),

    ("FG-SUV-BEV-16", "SA-PWR-EVS", 1), ("FG-SUV-BEV-16", "SA-BIW-SUVC", 1), ("FG-SUV-BEV-16", "SA-CHS-PLTM", 1),
    ("FG-SUV-BEV-16", "SA-CKP-PE", 1), ("FG-SUV-BEV-16", "SA-SET-5L", 1), ("FG-SUV-BEV-16", "SA-ELE-EV", 1),
    ("FG-SUV-BEV-16", "SA-WHL-18", 1), ("FG-SUV-BEV-16", "SA-BAT-E60", 1), ("FG-SUV-BEV-16", "SA-CHG-EV", 1),

    ("FG-SUV-BEV-17", "SA-PWR-EVD", 1), ("FG-SUV-BEV-17", "SA-BIW-SUVM", 1), ("FG-SUV-BEV-17", "SA-CHS-PLTX", 1),
    ("FG-SUV-BEV-17", "SA-CKP-PE", 1), ("FG-SUV-BEV-17", "SA-SET-5L", 1), ("FG-SUV-BEV-17", "SA-ELE-EV", 1),
    ("FG-SUV-BEV-17", "SA-WHL-18", 1), ("FG-SUV-BEV-17", "SA-BAT-E90", 1), ("FG-SUV-BEV-17", "SA-CHG-EV", 1),

    ("FG-MPV-BEV-18", "SA-PWR-EVS", 1), ("FG-MPV-BEV-18", "SA-BIW-MPV", 1), ("FG-MPV-BEV-18", "SA-CHS-PLTM", 1),
    ("FG-MPV-BEV-18", "SA-CKP-PE", 1), ("FG-MPV-BEV-18", "SA-SET-7L", 1), ("FG-MPV-BEV-18", "SA-ELE-EV", 1),
    ("FG-MPV-BEV-18", "SA-WHL-17", 1), ("FG-MPV-BEV-18", "SA-BAT-E72", 1), ("FG-MPV-BEV-18", "SA-CHG-EV", 1),

    ("FG-PKP-BEV-19", "SA-PWR-EVD", 1), ("FG-PKP-BEV-19", "SA-BIW-PKP", 1), ("FG-PKP-BEV-19", "SA-CHS-LDR", 1),
    ("FG-PKP-BEV-19", "SA-CKP-PE", 1), ("FG-PKP-BEV-19", "SA-SET-5L", 1), ("FG-PKP-BEV-19", "SA-ELE-EV", 1),
    ("FG-PKP-BEV-19", "SA-WHL-17LT", 1), ("FG-PKP-BEV-19", "SA-BAT-E90", 1), ("FG-PKP-BEV-19", "SA-CHG-EV", 1),

    ("FG-VAN-BEV-20", "SA-PWR-EVS", 1), ("FG-VAN-BEV-20", "SA-BIW-VAN", 1), ("FG-VAN-BEV-20", "SA-CHS-VAN", 1),
    ("FG-VAN-BEV-20", "SA-CKP-ME", 1), ("FG-VAN-BEV-20", "SA-SET-VAN", 1), ("FG-VAN-BEV-20", "SA-ELE-EV", 1),
    ("FG-VAN-BEV-20", "SA-WHL-17LT", 1), ("FG-VAN-BEV-20", "SA-BAT-E60", 1), ("FG-VAN-BEV-20", "SA-CHG-EV", 1),

    # ===== POWERTRAIN MODULES -> engine / transmission / e-drive / auxiliaries =====
    ("SA-PWR-G12", "SA-ENG-G12", 1), ("SA-PWR-G12", "SA-TRN-CVT", 1), ("SA-PWR-G12", "RM-ECU-ENG-G", 1),
    ("SA-PWR-G12", "RM-EXH-GAS", 1), ("SA-PWR-G12", "RM-RAD-S", 1), ("SA-PWR-G12", "RM-FTK-S", 1),

    ("SA-PWR-G15", "SA-ENG-G15", 1), ("SA-PWR-G15", "SA-TRN-CVT", 1), ("SA-PWR-G15", "RM-ECU-ENG-G", 1),
    ("SA-PWR-G15", "RM-EXH-GAS", 1), ("SA-PWR-G15", "RM-RAD-S", 1), ("SA-PWR-G15", "RM-FTK-S", 1),

    ("SA-PWR-G20T", "SA-ENG-G20T", 1), ("SA-PWR-G20T", "SA-TRN-AT8", 1), ("SA-PWR-G20T", "RM-ECU-ENG-G", 1),
    ("SA-PWR-G20T", "RM-EXH-GAS", 1), ("SA-PWR-G20T", "RM-RAD-L", 1), ("SA-PWR-G20T", "RM-FTK-S", 1),
    ("SA-PWR-G20T", "RM-TFC-AWD", 1),

    ("SA-PWR-D24A", "SA-ENG-D24", 1), ("SA-PWR-D24A", "SA-TRN-AT6", 1), ("SA-PWR-D24A", "RM-ECU-ENG-D", 1),
    ("SA-PWR-D24A", "RM-EXH-DSL", 1), ("SA-PWR-D24A", "RM-RAD-L", 1), ("SA-PWR-D24A", "RM-FTK-L", 1),
    ("SA-PWR-D24A", "RM-DEF-TNK", 1),

    ("SA-PWR-D24M", "SA-ENG-D24", 1), ("SA-PWR-D24M", "SA-TRN-MT6", 1), ("SA-PWR-D24M", "RM-ECU-ENG-D", 1),
    ("SA-PWR-D24M", "RM-EXH-DSL", 1), ("SA-PWR-D24M", "RM-RAD-L", 1), ("SA-PWR-D24M", "RM-FTK-L", 1),
    ("SA-PWR-D24M", "RM-DEF-TNK", 1),

    ("SA-PWR-D24X", "SA-ENG-D24", 1), ("SA-PWR-D24X", "SA-TRN-AT6", 1), ("SA-PWR-D24X", "RM-ECU-ENG-D", 1),
    ("SA-PWR-D24X", "RM-EXH-DSL", 1), ("SA-PWR-D24X", "RM-RAD-L", 1), ("SA-PWR-D24X", "RM-FTK-L", 1),
    ("SA-PWR-D24X", "RM-DEF-TNK", 1), ("SA-PWR-D24X", "RM-TFC-AWD", 1),

    ("SA-PWR-HEV15", "SA-ENG-H15", 1), ("SA-PWR-HEV15", "SA-TRN-EVA", 1), ("SA-PWR-HEV15", "SA-EMT-HVA", 1),
    ("SA-PWR-HEV15", "RM-ECU-HCU", 1), ("SA-PWR-HEV15", "RM-EXH-GAS", 1), ("SA-PWR-HEV15", "RM-RAD-S", 1),
    ("SA-PWR-HEV15", "RM-FTK-S", 1),

    ("SA-PWR-HEV20", "SA-ENG-H20", 1), ("SA-PWR-HEV20", "SA-TRN-EVB", 1), ("SA-PWR-HEV20", "SA-EMT-HVB", 1),
    ("SA-PWR-HEV20", "RM-ECU-HCU", 1), ("SA-PWR-HEV20", "RM-EXH-GAS", 1), ("SA-PWR-HEV20", "RM-RAD-S", 1),
    ("SA-PWR-HEV20", "RM-FTK-S", 1),

    ("SA-PWR-EVS", "SA-EMT-EVS", 1), ("SA-PWR-EVS", "RM-ECU-VCU", 1), ("SA-PWR-EVS", "RM-RAD-S", 1),
    ("SA-PWR-EVS", "RM-TMS-EV", 1),

    ("SA-PWR-EVD", "SA-EMT-EVS", 1), ("SA-PWR-EVD", "SA-EMT-EVR", 1), ("SA-PWR-EVD", "RM-ECU-VCU", 1),
    ("SA-PWR-EVD", "RM-RAD-L", 1), ("SA-PWR-EVD", "RM-TMS-EV", 1),

    # ===== ENGINE ASSEMBLIES -> purchased components =====
    ("SA-ENG-G12", "RM-BLK-G12", 1), ("SA-ENG-G12", "RM-HED-G12", 1), ("SA-ENG-G12", "RM-INJ-PFI", 3),
    ("SA-ENG-G12", "RM-SPK-IRI", 3), ("SA-ENG-G12", "RM-CHN-TIM", 1), ("SA-ENG-G12", "RM-OWP-SET", 1),
    ("SA-ENG-G12", "RM-ENM-SET", 1), ("SA-ENG-G12", "RM-EOL-5W30", 3.5),

    ("SA-ENG-G15", "RM-BLK-G15", 1), ("SA-ENG-G15", "RM-HED-G15", 1), ("SA-ENG-G15", "RM-INJ-PFI", 4),
    ("SA-ENG-G15", "RM-SPK-IRI", 4), ("SA-ENG-G15", "RM-CHN-TIM", 1), ("SA-ENG-G15", "RM-OWP-SET", 1),
    ("SA-ENG-G15", "RM-ENM-SET", 1), ("SA-ENG-G15", "RM-EOL-5W30", 4.0),

    ("SA-ENG-G20T", "RM-BLK-G20T", 1), ("SA-ENG-G20T", "RM-HED-G20T", 1), ("SA-ENG-G20T", "RM-TRB-G20T", 1),
    ("SA-ENG-G20T", "RM-INJ-GDI", 4), ("SA-ENG-G20T", "RM-SPK-IRI", 4), ("SA-ENG-G20T", "RM-CHN-TIM", 1),
    ("SA-ENG-G20T", "RM-OWP-SET", 1), ("SA-ENG-G20T", "RM-ENM-SET", 1), ("SA-ENG-G20T", "RM-EOL-5W30", 5.0),

    ("SA-ENG-D24", "RM-BLK-D24", 1), ("SA-ENG-D24", "RM-HED-D24", 1), ("SA-ENG-D24", "RM-TRB-D24", 1),
    ("SA-ENG-D24", "RM-INJ-CRD", 4), ("SA-ENG-D24", "RM-GLP-DSL", 4), ("SA-ENG-D24", "RM-HPF-CRD", 1),
    ("SA-ENG-D24", "RM-EGR-DSL", 1), ("SA-ENG-D24", "RM-CHN-TIM", 1), ("SA-ENG-D24", "RM-OWP-SET", 1),
    ("SA-ENG-D24", "RM-ENM-SET", 1), ("SA-ENG-D24", "RM-EOL-5W30", 7.0),

    ("SA-ENG-H15", "RM-BLK-H15", 1), ("SA-ENG-H15", "RM-HED-H15", 1), ("SA-ENG-H15", "RM-INJ-PFI", 4),
    ("SA-ENG-H15", "RM-SPK-IRI", 4), ("SA-ENG-H15", "RM-CHN-TIM", 1), ("SA-ENG-H15", "RM-OWP-SET", 1),
    ("SA-ENG-H15", "RM-ENM-SET", 1), ("SA-ENG-H15", "RM-EOL-5W30", 3.8),

    ("SA-ENG-H20", "RM-BLK-H20", 1), ("SA-ENG-H20", "RM-HED-H20", 1), ("SA-ENG-H20", "RM-INJ-GDI", 4),
    ("SA-ENG-H20", "RM-SPK-IRI", 4), ("SA-ENG-H20", "RM-CHN-TIM", 1), ("SA-ENG-H20", "RM-OWP-SET", 1),
    ("SA-ENG-H20", "RM-ENM-SET", 1), ("SA-ENG-H20", "RM-EOL-5W30", 4.5),

    # ===== TRANSMISSION ASSEMBLIES -> purchased components =====
    ("SA-TRN-CVT", "RM-TAX-CVT", 1), ("SA-TRN-CVT", "RM-TQC-CVT", 1), ("SA-TRN-CVT", "RM-ATF-FLD", 7.0),
    ("SA-TRN-AT8", "RM-TAX-AT8", 1), ("SA-TRN-AT8", "RM-TQC-AT8", 1), ("SA-TRN-AT8", "RM-ATF-FLD", 9.0),
    ("SA-TRN-AT6", "RM-TAX-AT6", 1), ("SA-TRN-AT6", "RM-TQC-AT6", 1), ("SA-TRN-AT6", "RM-ATF-FLD", 8.0),
    ("SA-TRN-MT6", "RM-TAX-MT6", 1), ("SA-TRN-MT6", "RM-CLU-MT6", 1), ("SA-TRN-MT6", "RM-ATF-FLD", 2.2),
    ("SA-TRN-EVA", "RM-TAX-EVA", 1), ("SA-TRN-EVA", "RM-ATF-FLD", 3.5),
    ("SA-TRN-EVB", "RM-TAX-EVB", 1), ("SA-TRN-EVB", "RM-ATF-FLD", 4.0),

    # ===== ELECTRIC DRIVE UNITS -> purchased components =====
    ("SA-EMT-HVA", "RM-MTR-60", 1), ("SA-EMT-HVA", "RM-INV-HYB", 1),
    ("SA-EMT-HVB", "RM-MTR-90", 1), ("SA-EMT-HVB", "RM-INV-HYB", 1),
    ("SA-EMT-EVS", "RM-MTR-150", 1), ("SA-EMT-EVS", "RM-INV-EV", 1), ("SA-EMT-EVS", "RM-RDG-S", 1),
    ("SA-EMT-EVR", "RM-MTR-200", 1), ("SA-EMT-EVR", "RM-INV-EV", 1), ("SA-EMT-EVR", "RM-RDG-L", 1),

    # ===== BATTERY: pack -> cell module -> cell (deepest branch) =====
    ("SA-BMD-LFP", "RM-CEL-LFP", 6), ("SA-BMD-LFP", "RM-BUS-MOD", 1), ("SA-BMD-LFP", "RM-CSC-MOD", 1),
    ("SA-BMD-LFP", "RM-TIM-PAD", 1),
    ("SA-BMD-NMC", "RM-CEL-NMC", 12), ("SA-BMD-NMC", "RM-BUS-MOD", 1), ("SA-BMD-NMC", "RM-CSC-MOD", 1),
    ("SA-BMD-NMC", "RM-TIM-PAD", 1),
    ("SA-BMD-HEV", "RM-CEL-HEV", 36), ("SA-BMD-HEV", "RM-BUS-MOD", 1), ("SA-BMD-HEV", "RM-CSC-MOD", 1),

    ("SA-BAT-HEV", "SA-BMD-HEV", 2), ("SA-BAT-HEV", "RM-BMS-HEV", 1), ("SA-BAT-HEV", "RM-ENC-HEV", 1),
    ("SA-BAT-HEV", "RM-MSD-HV", 1),
    ("SA-BAT-PHEV", "SA-BMD-NMC", 6), ("SA-BAT-PHEV", "RM-BMS-EV", 1), ("SA-BAT-PHEV", "RM-ENC-PHEV", 1),
    ("SA-BAT-PHEV", "RM-CLP-EV", 2), ("SA-BAT-PHEV", "RM-HVJ-EV", 1), ("SA-BAT-PHEV", "RM-MSD-HV", 1),
    ("SA-BAT-E40", "SA-BMD-LFP", 20), ("SA-BAT-E40", "RM-BMS-EV", 1), ("SA-BAT-E40", "RM-ENC-EVS", 1),
    ("SA-BAT-E40", "RM-CLP-EV", 5), ("SA-BAT-E40", "RM-HVJ-EV", 1), ("SA-BAT-E40", "RM-MSD-HV", 1),
    ("SA-BAT-E60", "SA-BMD-NMC", 20), ("SA-BAT-E60", "RM-BMS-EV", 1), ("SA-BAT-E60", "RM-ENC-EVS", 1),
    ("SA-BAT-E60", "RM-CLP-EV", 5), ("SA-BAT-E60", "RM-HVJ-EV", 1), ("SA-BAT-E60", "RM-MSD-HV", 1),
    ("SA-BAT-E72", "SA-BMD-NMC", 24), ("SA-BAT-E72", "RM-BMS-EV", 1), ("SA-BAT-E72", "RM-ENC-EVL", 1),
    ("SA-BAT-E72", "RM-CLP-EV", 6), ("SA-BAT-E72", "RM-HVJ-EV", 1), ("SA-BAT-E72", "RM-MSD-HV", 1),
    ("SA-BAT-E90", "SA-BMD-NMC", 30), ("SA-BAT-E90", "RM-BMS-EV", 1), ("SA-BAT-E90", "RM-ENC-EVL", 1),
    ("SA-BAT-E90", "RM-CLP-EV", 8), ("SA-BAT-E90", "RM-HVJ-EV", 1), ("SA-BAT-E90", "RM-MSD-HV", 1),

    # ===== CHARGING SYSTEMS =====
    ("SA-CHG-PHEV", "RM-OBC-37", 1), ("SA-CHG-PHEV", "RM-INL-T2", 1), ("SA-CHG-PHEV", "RM-CBL-EVSE", 1),
    ("SA-CHG-EV", "RM-OBC-110", 1), ("SA-CHG-EV", "RM-INL-CCS2", 1), ("SA-CHG-EV", "RM-CBL-EVSE", 1),

    # ===== ELECTRICAL MODULES & ADAS =====
    ("SA-ELE-S", "RM-HRN-BDY-S", 1), ("SA-ELE-S", "RM-HRN-DOR", 1), ("SA-ELE-S", "RM-HRN-ENG", 1),
    ("SA-ELE-S", "RM-BAT-12V-PB", 1), ("SA-ELE-S", "RM-ALT-STD", 1), ("SA-ELE-S", "RM-STM-STD", 1),
    ("SA-ELE-S", "RM-BCM-STD", 1), ("SA-ELE-S", "RM-FSB-SET", 1), ("SA-ELE-S", "RM-SNS-PRK", 4),
    ("SA-ELE-S", "RM-CAM-RVW", 1), ("SA-ELE-S", "RM-KEY-IMM", 2),

    ("SA-ELE-P", "RM-HRN-BDY-P", 1), ("SA-ELE-P", "RM-HRN-DOR", 1), ("SA-ELE-P", "RM-HRN-ENG", 1),
    ("SA-ELE-P", "RM-BAT-12V-PB", 1), ("SA-ELE-P", "RM-ALT-STD", 1), ("SA-ELE-P", "RM-STM-STD", 1),
    ("SA-ELE-P", "RM-BCM-STD", 1), ("SA-ELE-P", "RM-FSB-SET", 1), ("SA-ELE-P", "RM-SNS-PRK", 8),
    ("SA-ELE-P", "RM-CAM-360", 1), ("SA-ELE-P", "RM-KEY-SMT", 2), ("SA-ELE-P", "RM-TCU-TEL", 1),
    ("SA-ELE-P", "SA-ADAS-L2", 1),

    ("SA-ELE-HEV", "RM-HRN-BDY-P", 1), ("SA-ELE-HEV", "RM-HRN-DOR", 1), ("SA-ELE-HEV", "RM-HRN-ENG", 1),
    ("SA-ELE-HEV", "RM-HRN-HV-HEV", 1), ("SA-ELE-HEV", "RM-BAT-12V-LI", 1), ("SA-ELE-HEV", "RM-STM-STD", 1),
    ("SA-ELE-HEV", "RM-BCM-STD", 1), ("SA-ELE-HEV", "RM-FSB-SET", 1), ("SA-ELE-HEV", "RM-SNS-PRK", 4),
    ("SA-ELE-HEV", "RM-CAM-RVW", 1), ("SA-ELE-HEV", "RM-KEY-SMT", 2), ("SA-ELE-HEV", "RM-TCU-TEL", 1),
    ("SA-ELE-HEV", "RM-DCDC-HV", 1), ("SA-ELE-HEV", "SA-ADAS-L1", 1),

    ("SA-ELE-EV", "RM-HRN-BDY-P", 1), ("SA-ELE-EV", "RM-HRN-DOR", 1), ("SA-ELE-EV", "RM-HRN-HV-EV", 1),
    ("SA-ELE-EV", "RM-BAT-12V-LI", 1), ("SA-ELE-EV", "RM-BCM-STD", 1), ("SA-ELE-EV", "RM-FSB-SET", 1),
    ("SA-ELE-EV", "RM-SNS-PRK", 8), ("SA-ELE-EV", "RM-CAM-360", 1), ("SA-ELE-EV", "RM-KEY-SMT", 2),
    ("SA-ELE-EV", "RM-TCU-TEL", 1), ("SA-ELE-EV", "RM-DCDC-HV", 1), ("SA-ELE-EV", "RM-AVAS", 1),
    ("SA-ELE-EV", "SA-ADAS-L2", 1),

    ("SA-ADAS-L1", "RM-CAM-FRT", 1), ("SA-ADAS-L1", "RM-RDR-FRT", 1), ("SA-ADAS-L1", "RM-ADC-L1", 1),
    ("SA-ADAS-L2", "RM-CAM-FRT", 1), ("SA-ADAS-L2", "RM-RDR-FRT", 1), ("SA-ADAS-L2", "RM-RDR-CRN", 4),
    ("SA-ADAS-L2", "RM-DMS-CAM", 1), ("SA-ADAS-L2", "RM-ADC-L2", 1),

    # ===== BODY-IN-WHITE (shell, closures, bumpers, lamps, glazing, mirrors, paint) =====
    ("SA-BIW-HB", "RM-BSH-HB", 1), ("SA-BIW-HB", "RM-DRS-C", 1), ("SA-BIW-HB", "RM-BMP-S", 1),
    ("SA-BIW-HB", "RM-HLP-LED", 1), ("SA-BIW-HB", "RM-TLP-LED", 1), ("SA-BIW-HB", "RM-GLZ-S", 1),
    ("SA-BIW-HB", "RM-MIR-STD", 1), ("SA-BIW-HB", "RM-PNT-BSC", 3.5), ("SA-BIW-HB", "RM-PNT-CLR", 3.0),

    ("SA-BIW-SDN", "RM-BSH-SDN", 1), ("SA-BIW-SDN", "RM-DRS-C", 1), ("SA-BIW-SDN", "RM-BMP-S", 1),
    ("SA-BIW-SDN", "RM-HLP-LED", 1), ("SA-BIW-SDN", "RM-TLP-LED", 1), ("SA-BIW-SDN", "RM-GLZ-S", 1),
    ("SA-BIW-SDN", "RM-MIR-STD", 1), ("SA-BIW-SDN", "RM-PNT-BSC", 4.0), ("SA-BIW-SDN", "RM-PNT-CLR", 3.5),

    ("SA-BIW-SUVC", "RM-BSH-SUVC", 1), ("SA-BIW-SUVC", "RM-DRS-C", 1), ("SA-BIW-SUVC", "RM-BMP-S", 1),
    ("SA-BIW-SUVC", "RM-HLP-LED", 1), ("SA-BIW-SUVC", "RM-TLP-LED", 1), ("SA-BIW-SUVC", "RM-GLZ-S", 1),
    ("SA-BIW-SUVC", "RM-MIR-STD", 1), ("SA-BIW-SUVC", "RM-PNT-BSC", 4.5), ("SA-BIW-SUVC", "RM-PNT-CLR", 3.8),

    ("SA-BIW-SUVM", "RM-BSH-SUVM", 1), ("SA-BIW-SUVM", "RM-DRS-L", 1), ("SA-BIW-SUVM", "RM-BMP-L", 1),
    ("SA-BIW-SUVM", "RM-HLP-LED", 1), ("SA-BIW-SUVM", "RM-TLP-LED", 1), ("SA-BIW-SUVM", "RM-GLZ-L", 1),
    ("SA-BIW-SUVM", "RM-MIR-STD", 1), ("SA-BIW-SUVM", "RM-PNT-BSC", 5.5), ("SA-BIW-SUVM", "RM-PNT-CLR", 4.5),

    ("SA-BIW-MPV", "RM-BSH-MPV", 1), ("SA-BIW-MPV", "RM-DRS-L", 1), ("SA-BIW-MPV", "RM-BMP-L", 1),
    ("SA-BIW-MPV", "RM-HLP-LED", 1), ("SA-BIW-MPV", "RM-TLP-LED", 1), ("SA-BIW-MPV", "RM-GLZ-L", 1),
    ("SA-BIW-MPV", "RM-MIR-STD", 1), ("SA-BIW-MPV", "RM-PNT-BSC", 6.0), ("SA-BIW-MPV", "RM-PNT-CLR", 5.0),

    ("SA-BIW-PKP", "RM-BSH-PKP", 1), ("SA-BIW-PKP", "RM-DRS-L", 1), ("SA-BIW-PKP", "RM-BMP-L", 1),
    ("SA-BIW-PKP", "RM-HLP-LED", 1), ("SA-BIW-PKP", "RM-TLP-LED", 1), ("SA-BIW-PKP", "RM-GLZ-L", 1),
    ("SA-BIW-PKP", "RM-MIR-STD", 1), ("SA-BIW-PKP", "RM-CGB-PKP", 1), ("SA-BIW-PKP", "RM-PNT-BSC", 6.0),
    ("SA-BIW-PKP", "RM-PNT-CLR", 4.5),

    ("SA-BIW-VAN", "RM-BSH-VAN", 1), ("SA-BIW-VAN", "RM-DRS-L", 1), ("SA-BIW-VAN", "RM-BMP-L", 1),
    ("SA-BIW-VAN", "RM-HLP-LED", 1), ("SA-BIW-VAN", "RM-TLP-LED", 1), ("SA-BIW-VAN", "RM-GLZ-L", 1),
    ("SA-BIW-VAN", "RM-MIR-STD", 1), ("SA-BIW-VAN", "RM-SLD-VAN", 1), ("SA-BIW-VAN", "RM-PNT-BSC", 7.0),
    ("SA-BIW-VAN", "RM-PNT-CLR", 5.5),

    # ===== CHASSIS MODULES -> suspension / brake / steering assemblies =====
    ("SA-CHS-PLTS", "SA-SUS-FRT", 1), ("SA-CHS-PLTS", "SA-SUS-RTB", 1), ("SA-CHS-PLTS", "SA-BRK-C", 1),
    ("SA-CHS-PLTS", "SA-STR-EPS", 1),
    ("SA-CHS-PLTM", "SA-SUS-FRT", 1), ("SA-CHS-PLTM", "SA-SUS-RML", 1), ("SA-CHS-PLTM", "SA-BRK-C", 1),
    ("SA-CHS-PLTM", "SA-STR-EPS", 1),
    ("SA-CHS-PLTX", "SA-SUS-FRT", 1), ("SA-CHS-PLTX", "SA-SUS-RML", 1), ("SA-CHS-PLTX", "SA-BRK-H", 1),
    ("SA-CHS-PLTX", "SA-STR-EPS", 1),
    ("SA-CHS-LDR", "RM-LDR-FRM", 1), ("SA-CHS-LDR", "SA-SUS-FRT", 1), ("SA-CHS-LDR", "SA-SUS-RLS", 1),
    ("SA-CHS-LDR", "SA-BRK-H", 1), ("SA-CHS-LDR", "SA-STR-EPS", 1),
    ("SA-CHS-VAN", "RM-UBF-VAN", 1), ("SA-CHS-VAN", "SA-SUS-FRT", 1), ("SA-CHS-VAN", "SA-SUS-RLS", 1),
    ("SA-CHS-VAN", "SA-BRK-H", 1), ("SA-CHS-VAN", "SA-STR-EPS", 1),

    ("SA-SUS-FRT", "RM-STR-FRT", 2), ("SA-SUS-FRT", "RM-LCA-FRT", 2), ("SA-SUS-FRT", "RM-KNK-FRT", 2),
    ("SA-SUS-FRT", "RM-SUB-FRT", 1),
    ("SA-SUS-RTB", "RM-TBA-RR", 1), ("SA-SUS-RTB", "RM-SPD-RR", 1),
    ("SA-SUS-RML", "RM-MLA-RR", 1), ("SA-SUS-RML", "RM-SPD-RR", 1),
    ("SA-SUS-RLS", "RM-RAX-RR", 1), ("SA-SUS-RLS", "RM-LSP-RR", 2), ("SA-SUS-RLS", "RM-DMP-RR", 2),

    ("SA-BRK-C", "RM-BFR-C", 1), ("SA-BRK-C", "RM-BRR-C", 1), ("SA-BRK-C", "RM-ABS-ESC", 1),
    ("SA-BRK-C", "RM-ABS-WSS", 4), ("SA-BRK-C", "RM-BMC-STD", 1), ("SA-BRK-C", "RM-EPB-ACT", 2),
    ("SA-BRK-C", "RM-BRF-DOT4", 1.0),
    ("SA-BRK-H", "RM-BFR-H", 1), ("SA-BRK-H", "RM-BRR-H", 1), ("SA-BRK-H", "RM-ABS-ESC", 1),
    ("SA-BRK-H", "RM-ABS-WSS", 4), ("SA-BRK-H", "RM-BMC-STD", 1), ("SA-BRK-H", "RM-EPB-ACT", 2),
    ("SA-BRK-H", "RM-BRF-DOT4", 1.2),

    ("SA-STR-EPS", "RM-RCK-EPS", 1), ("SA-STR-EPS", "RM-EPM-EPS", 1), ("SA-STR-EPS", "RM-STC-STD", 1),

    # ===== WHEEL & TYRE SETS =====
    ("SA-WHL-15", "RM-WHL-ALU-15", 4), ("SA-WHL-15", "RM-TYR-15", 4), ("SA-WHL-15", "RM-WHL-HW", 1),
    ("SA-WHL-16", "RM-WHL-ALU-16", 4), ("SA-WHL-16", "RM-TYR-16", 4), ("SA-WHL-16", "RM-WHL-HW", 1),
    ("SA-WHL-17", "RM-WHL-ALU-17", 4), ("SA-WHL-17", "RM-TYR-17", 4), ("SA-WHL-17", "RM-WHL-HW", 1),
    ("SA-WHL-18", "RM-WHL-ALU-18", 4), ("SA-WHL-18", "RM-TYR-18", 4), ("SA-WHL-18", "RM-WHL-HW", 1),
    ("SA-WHL-17LT", "RM-WHL-ALU-17", 4), ("SA-WHL-17LT", "RM-TYR-17LT", 4), ("SA-WHL-17LT", "RM-WHL-HW", 1),

    # ===== COCKPIT MODULES & HVAC =====
    ("SA-CKP-B", "RM-DSH-B", 1), ("SA-CKP-B", "RM-CLS-ANA", 1), ("SA-CKP-B", "RM-HDU-7", 1),
    ("SA-CKP-B", "RM-STW-STD", 1), ("SA-CKP-B", "RM-ARB-PAS", 1), ("SA-CKP-B", "RM-PED-SET", 1),
    ("SA-CKP-B", "RM-AUD-6", 1), ("SA-CKP-B", "RM-TRM-SET", 1), ("SA-CKP-B", "SA-HVC-MAN", 1),

    ("SA-CKP-M", "RM-DSH-M", 1), ("SA-CKP-M", "RM-CLS-TFT", 1), ("SA-CKP-M", "RM-HDU-9", 1),
    ("SA-CKP-M", "RM-STW-PRM", 1), ("SA-CKP-M", "RM-ARB-PAS", 1), ("SA-CKP-M", "RM-ARB-KNEE", 1),
    ("SA-CKP-M", "RM-PED-SET", 1), ("SA-CKP-M", "RM-AUD-6", 1), ("SA-CKP-M", "RM-TRM-SET", 1),
    ("SA-CKP-M", "SA-HVC-AUT", 1),

    ("SA-CKP-P", "RM-DSH-P", 1), ("SA-CKP-P", "RM-CLS-TFT12", 1), ("SA-CKP-P", "RM-HDU-12", 1),
    ("SA-CKP-P", "RM-STW-PRM", 1), ("SA-CKP-P", "RM-ARB-PAS", 1), ("SA-CKP-P", "RM-ARB-KNEE", 1),
    ("SA-CKP-P", "RM-PED-SET", 1), ("SA-CKP-P", "RM-AUD-8", 1), ("SA-CKP-P", "RM-TRM-SET", 1),
    ("SA-CKP-P", "SA-HVC-AUT", 1),

    ("SA-CKP-ME", "RM-DSH-M", 1), ("SA-CKP-ME", "RM-CLS-TFT", 1), ("SA-CKP-ME", "RM-HDU-9", 1),
    ("SA-CKP-ME", "RM-STW-PRM", 1), ("SA-CKP-ME", "RM-ARB-PAS", 1), ("SA-CKP-ME", "RM-ARB-KNEE", 1),
    ("SA-CKP-ME", "RM-PED-SET", 1), ("SA-CKP-ME", "RM-AUD-6", 1), ("SA-CKP-ME", "RM-TRM-SET", 1),
    ("SA-CKP-ME", "SA-HVC-EV", 1),

    ("SA-CKP-PE", "RM-DSH-P", 1), ("SA-CKP-PE", "RM-CLS-TFT12", 1), ("SA-CKP-PE", "RM-HDU-12", 1),
    ("SA-CKP-PE", "RM-STW-PRM", 1), ("SA-CKP-PE", "RM-ARB-PAS", 1), ("SA-CKP-PE", "RM-ARB-KNEE", 1),
    ("SA-CKP-PE", "RM-PED-SET", 1), ("SA-CKP-PE", "RM-AUD-8", 1), ("SA-CKP-PE", "RM-TRM-SET", 1),
    ("SA-CKP-PE", "SA-HVC-EV", 1),

    ("SA-HVC-MAN", "RM-HVC-CSE-M", 1), ("SA-HVC-MAN", "RM-BLW-MTR", 1), ("SA-HVC-MAN", "RM-EVP-CORE", 1),
    ("SA-HVC-MAN", "RM-CND-AC", 1), ("SA-HVC-MAN", "RM-ACC-MECH", 1),
    ("SA-HVC-AUT", "RM-HVC-CSE-A", 1), ("SA-HVC-AUT", "RM-BLW-MTR", 1), ("SA-HVC-AUT", "RM-EVP-CORE", 1),
    ("SA-HVC-AUT", "RM-CND-AC", 1), ("SA-HVC-AUT", "RM-ACC-MECH", 1), ("SA-HVC-AUT", "RM-HVC-CTL", 1),
    ("SA-HVC-EV", "RM-HVC-CSE-A", 1), ("SA-HVC-EV", "RM-BLW-MTR", 1), ("SA-HVC-EV", "RM-EVP-CORE", 1),
    ("SA-HVC-EV", "RM-CND-AC", 1), ("SA-HVC-EV", "RM-ACC-ELE", 1), ("SA-HVC-EV", "RM-HVC-CTL", 1),
    ("SA-HVC-EV", "RM-PTC-HTR", 1),

    # ===== SEAT SETS (quantities of foam/cover are per seat row) =====
    ("SA-SET-5F", "RM-SFR-FM", 1), ("SA-SET-5F", "RM-SFR-R", 1), ("SA-SET-5F", "RM-FOM-SEAT", 2),
    ("SA-SET-5F", "RM-COV-FAB", 2), ("SA-SET-5F", "RM-SBT-SET", 1),
    ("SA-SET-5L", "RM-SFR-FP", 1), ("SA-SET-5L", "RM-SFR-R", 1), ("SA-SET-5L", "RM-FOM-SEAT", 2),
    ("SA-SET-5L", "RM-COV-LTH", 2), ("SA-SET-5L", "RM-SHT-HEAT", 1), ("SA-SET-5L", "RM-SBT-SET", 1),
    ("SA-SET-7F", "RM-SFR-FM", 1), ("SA-SET-7F", "RM-SFR-R", 1), ("SA-SET-7F", "RM-SFR-3R", 1),
    ("SA-SET-7F", "RM-FOM-SEAT", 3), ("SA-SET-7F", "RM-COV-FAB", 3), ("SA-SET-7F", "RM-SBT-SET", 1),
    ("SA-SET-7L", "RM-SFR-FP", 1), ("SA-SET-7L", "RM-SFR-R", 1), ("SA-SET-7L", "RM-SFR-3R", 1),
    ("SA-SET-7L", "RM-FOM-SEAT", 3), ("SA-SET-7L", "RM-COV-LTH", 3), ("SA-SET-7L", "RM-SHT-HEAT", 1),
    ("SA-SET-7L", "RM-SBT-SET", 1),
    ("SA-SET-VAN", "RM-SFR-VAN", 1), ("SA-SET-VAN", "RM-FOM-SEAT", 1), ("SA-SET-VAN", "RM-COV-VNL-VAN", 1),
    ("SA-SET-VAN", "RM-SBT-SET", 1),

    # ===== SOKRATESCAR: vehicle -> modules -> assemblies -> raw materials (PT Fandi / PT Chris only) =====
    ("FG-SDN-SKR-21", "SA-SKR-PWR", 1), ("FG-SDN-SKR-21", "SA-SKR-BODY", 1),
    ("FG-SDN-SKR-21", "SA-SKR-INT", 1), ("FG-SDN-SKR-21", "SA-SKR-ELE", 1),
    ("SA-SKR-PWR", "SA-SKR-ENG", 1), ("SA-SKR-PWR", "RM-SKR-TRN", 1), ("SA-SKR-PWR", "RM-SKR-ECU", 1),
    ("SA-SKR-PWR", "RM-SKR-EXH", 1), ("SA-SKR-PWR", "RM-SKR-RAD", 1), ("SA-SKR-PWR", "RM-SKR-FTK", 1),
    ("SA-SKR-ENG", "RM-SKR-BLK", 1), ("SA-SKR-ENG", "RM-SKR-HED", 1), ("SA-SKR-ENG", "RM-SKR-INJ", 4),
    ("SA-SKR-ENG", "RM-SKR-SPK", 4), ("SA-SKR-ENG", "RM-SKR-OIL", 4.0),
    ("SA-SKR-BODY", "SA-SKR-CHS", 1), ("SA-SKR-BODY", "RM-SKR-BSH", 1), ("SA-SKR-BODY", "RM-SKR-DRS", 1),
    ("SA-SKR-BODY", "RM-SKR-BMP", 1), ("SA-SKR-BODY", "RM-SKR-GLZ", 1), ("SA-SKR-BODY", "RM-SKR-PNT", 7.5),
    ("SA-SKR-CHS", "RM-SKR-SUSF", 1), ("SA-SKR-CHS", "RM-SKR-SUSR", 1), ("SA-SKR-CHS", "RM-SKR-BRK", 1),
    ("SA-SKR-CHS", "RM-SKR-STR", 1), ("SA-SKR-CHS", "RM-SKR-WHL", 1),
    ("SA-SKR-INT", "RM-SKR-DSH", 1), ("SA-SKR-INT", "RM-SKR-SEAT", 1), ("SA-SKR-INT", "RM-SKR-HVC", 1),
    ("SA-SKR-INT", "RM-SKR-HDU", 1), ("SA-SKR-INT", "RM-SKR-TRM", 1),
    ("SA-SKR-ELE", "RM-SKR-HRN", 1), ("SA-SKR-ELE", "RM-SKR-BAT12", 1), ("SA-SKR-ELE", "RM-SKR-BCM", 1),
    ("SA-SKR-ELE", "RM-SKR-ALT", 1), ("SA-SKR-ELE", "RM-SKR-STM", 1), ("SA-SKR-ELE", "RM-SKR-LGT", 1),
]

# sku: (physical stock, safety stock)  -- allocated starts at 0.0 for every item
INVENTORY = {
    # ---- finished vehicles (units in plant yard / dealer-ready stock) ----
    "FG-HB-ICE-01": (48, 20), "FG-SDN-ICE-02": (36, 15), "FG-SUV-ICE-03": (42, 18), "FG-SUV-ICE-04": (14, 6),
    "FG-MPV-ICE-05": (55, 20), "FG-PKP-DSL-06": (28, 12), "FG-SUV-DSL-07": (12, 5), "FG-VAN-DSL-08": (18, 8),
    "FG-HB-HEV-09": (22, 10), "FG-SDN-HEV-10": (16, 8), "FG-SUV-HEV-11": (20, 8), "FG-MPV-HEV-12": (15, 6),
    "FG-SUV-PHEV-13": (8, 4), "FG-HB-BEV-14": (30, 12), "FG-SDN-BEV-15": (18, 8), "FG-SUV-BEV-16": (24, 10),
    "FG-SUV-BEV-17": (6, 3), "FG-MPV-BEV-18": (10, 5), "FG-PKP-BEV-19": (7, 3), "FG-VAN-BEV-20": (12, 6),

    # ---- sub-parts: powertrain modules / engines / transmissions / drive units ----
    "SA-PWR-G12": (40, 15), "SA-PWR-G15": (90, 30), "SA-PWR-G20T": (25, 10), "SA-PWR-D24A": (45, 15),
    "SA-PWR-D24M": (22, 8), "SA-PWR-D24X": (18, 8), "SA-PWR-HEV15": (50, 20), "SA-PWR-HEV20": (45, 18),
    "SA-PWR-EVS": (70, 25), "SA-PWR-EVD": (20, 8),
    "SA-ENG-G12": (45, 15), "SA-ENG-G15": (100, 35), "SA-ENG-G20T": (28, 10), "SA-ENG-D24": (80, 30),
    "SA-ENG-H15": (55, 20), "SA-ENG-H20": (50, 20),
    "SA-TRN-CVT": (150, 50), "SA-TRN-AT8": (30, 12), "SA-TRN-AT6": (60, 20), "SA-TRN-MT6": (25, 10),
    "SA-TRN-EVA": (55, 20), "SA-TRN-EVB": (50, 20),
    "SA-EMT-HVA": (60, 22), "SA-EMT-HVB": (55, 22), "SA-EMT-EVS": (110, 40), "SA-EMT-EVR": (30, 12),

    # ---- sub-parts: electrical / battery systems ----
    "SA-BMD-LFP": (240, 80), "SA-BMD-NMC": (900, 300), "SA-BMD-HEV": (150, 50),
    "SA-BAT-HEV": (70, 25), "SA-BAT-PHEV": (14, 6), "SA-BAT-E40": (26, 10), "SA-BAT-E60": (40, 16),
    "SA-BAT-E72": (12, 5), "SA-BAT-E90": (14, 6),
    "SA-CHG-PHEV": (14, 6), "SA-CHG-EV": (90, 30),
    "SA-ELE-S": (200, 70), "SA-ELE-P": (35, 12), "SA-ELE-HEV": (110, 40), "SA-ELE-EV": (120, 40),
    "SA-ADAS-L1": (120, 40), "SA-ADAS-L2": (150, 50),

    # ---- sub-parts: body & chassis ----
    "SA-BIW-HB": (35, 12), "SA-BIW-SDN": (28, 10), "SA-BIW-SUVC": (30, 10), "SA-BIW-SUVM": (36, 12),
    "SA-BIW-MPV": (32, 12), "SA-BIW-PKP": (24, 10), "SA-BIW-VAN": (20, 8),
    "SA-CHS-PLTS": (40, 15), "SA-CHS-PLTM": (85, 30), "SA-CHS-PLTX": (45, 18), "SA-CHS-LDR": (35, 14),
    "SA-CHS-VAN": (22, 9),
    "SA-SUS-FRT": (220, 80), "SA-SUS-RTB": (60, 20), "SA-SUS-RML": (110, 40), "SA-SUS-RLS": (70, 25),
    "SA-BRK-C": (170, 60), "SA-BRK-H": (110, 40), "SA-STR-EPS": (280, 100),
    "SA-WHL-15": (40, 15), "SA-WHL-16": (130, 45), "SA-WHL-17": (60, 20), "SA-WHL-18": (75, 25),
    "SA-WHL-17LT": (65, 22),

    # ---- sub-parts: interior / cockpit ----
    "SA-CKP-B": (60, 20), "SA-CKP-M": (110, 40), "SA-CKP-P": (45, 16), "SA-CKP-ME": (50, 18), "SA-CKP-PE": (55, 20),
    "SA-HVC-MAN": (65, 22), "SA-HVC-AUT": (150, 50), "SA-HVC-EV": (110, 40),
    "SA-SET-5F": (130, 45), "SA-SET-5L": (110, 40), "SA-SET-7F": (30, 12), "SA-SET-7L": (50, 18),
    "SA-SET-VAN": (28, 10),

    # ---- purchased: engine & fluids ----
    "RM-BLK-G12": (60, 20), "RM-HED-G12": (60, 20), "RM-BLK-G15": (130, 45), "RM-HED-G15": (130, 45),
    "RM-BLK-G20T": (40, 15), "RM-HED-G20T": (40, 15), "RM-BLK-D24": (100, 35), "RM-HED-D24": (100, 35),
    "RM-BLK-H15": (70, 25), "RM-HED-H15": (70, 25), "RM-BLK-H20": (65, 25), "RM-HED-H20": (65, 25),
    "RM-TRB-G20T": (45, 15), "RM-TRB-D24": (95, 30), "RM-INJ-PFI": (1200, 400), "RM-INJ-GDI": (600, 200),
    "RM-INJ-CRD": (450, 160), "RM-SPK-IRI": (2000, 600), "RM-GLP-DSL": (420, 150), "RM-CHN-TIM": (330, 110),
    "RM-OWP-SET": (330, 110), "RM-ENM-SET": (340, 110), "RM-HPF-CRD": (95, 30), "RM-EGR-DSL": (95, 30),
    "RM-ECU-ENG-G": (350, 120), "RM-ECU-ENG-D": (110, 40), "RM-EOL-5W30": (4000, 1200),

    # ---- purchased: transmission, driveline & e-drive ----
    "RM-TAX-CVT": (160, 55), "RM-TQC-CVT": (160, 55), "RM-TAX-AT8": (35, 12), "RM-TQC-AT8": (35, 12),
    "RM-TAX-AT6": (65, 22), "RM-TQC-AT6": (65, 22), "RM-TAX-MT6": (28, 10), "RM-CLU-MT6": (28, 10),
    "RM-TAX-EVA": (60, 22), "RM-TAX-EVB": (55, 22), "RM-ATF-FLD": (3500, 1000), "RM-TFC-AWD": (45, 18),
    "RM-MTR-60": (65, 25), "RM-MTR-90": (60, 25), "RM-MTR-150": (120, 45), "RM-MTR-200": (35, 14),
    "RM-INV-HYB": (130, 50), "RM-INV-EV": (160, 60), "RM-RDG-S": (125, 45), "RM-RDG-L": (38, 15),

    # ---- purchased: powertrain-level auxiliaries ----
    "RM-ECU-HCU": (120, 45), "RM-ECU-VCU": (130, 45), "RM-EXH-GAS": (330, 110), "RM-EXH-DSL": (110, 40),
    "RM-RAD-S": (320, 110), "RM-RAD-L": (150, 50), "RM-FTK-S": (330, 110), "RM-FTK-L": (110, 40),
    "RM-DEF-TNK": (85, 30), "RM-TMS-EV": (130, 45),

    # ---- purchased: battery systems & charging ----
    "RM-CEL-LFP": (6000, 2000), "RM-CEL-NMC": (25000, 8000), "RM-CEL-HEV": (8000, 2500),
    "RM-BUS-MOD": (1300, 450), "RM-CSC-MOD": (1300, 450), "RM-TIM-PAD": (1100, 400),
    "RM-BMS-HEV": (80, 30), "RM-BMS-EV": (140, 50), "RM-ENC-HEV": (80, 30), "RM-ENC-PHEV": (16, 6),
    "RM-ENC-EVS": (70, 25), "RM-ENC-EVL": (28, 10), "RM-CLP-EV": (650, 220), "RM-HVJ-EV": (145, 50),
    "RM-MSD-HV": (230, 80), "RM-OBC-37": (16, 6), "RM-OBC-110": (110, 40), "RM-INL-T2": (20, 8),
    "RM-INL-CCS2": (115, 40), "RM-CBL-EVSE": (140, 50),

    # ---- purchased: body, paint & closures ----
    "RM-BSH-HB": (40, 15), "RM-BSH-SDN": (30, 12), "RM-BSH-SUVC": (35, 12), "RM-BSH-SUVM": (40, 15),
    "RM-BSH-MPV": (35, 12), "RM-BSH-PKP": (26, 10), "RM-BSH-VAN": (22, 9),
    "RM-DRS-C": (100, 35), "RM-DRS-L": (140, 50), "RM-BMP-S": (130, 45), "RM-BMP-L": (160, 55),
    "RM-HLP-LED": (300, 100), "RM-TLP-LED": (300, 100), "RM-GLZ-S": (110, 40), "RM-GLZ-L": (150, 50),
    "RM-MIR-STD": (300, 100), "RM-PNT-BSC": (5500, 1800), "RM-PNT-CLR": (4500, 1500),
    "RM-CGB-PKP": (40, 15), "RM-SLD-VAN": (32, 12),

    # ---- purchased: suspension, brakes, steering, frames ----
    "RM-STR-FRT": (900, 300), "RM-LCA-FRT": (900, 300), "RM-KNK-FRT": (900, 300), "RM-SUB-FRT": (450, 150),
    "RM-TBA-RR": (65, 22), "RM-MLA-RR": (115, 40), "RM-RAX-RR": (75, 26), "RM-LSP-RR": (300, 100),
    "RM-SPD-RR": (180, 60), "RM-DMP-RR": (300, 100),
    "RM-BFR-C": (180, 60), "RM-BRR-C": (180, 60), "RM-BFR-H": (120, 42), "RM-BRR-H": (120, 42),
    "RM-ABS-ESC": (290, 100), "RM-ABS-WSS": (1200, 400), "RM-BMC-STD": (290, 100), "RM-EPB-ACT": (580, 200),
    "RM-BRF-DOT4": (500, 150), "RM-RCK-EPS": (290, 100), "RM-EPM-EPS": (290, 100), "RM-STC-STD": (300, 100),
    "RM-LDR-FRM": (40, 15), "RM-UBF-VAN": (24, 10),

    # ---- purchased: wheels & tyres ----
    "RM-WHL-ALU-15": (180, 60), "RM-WHL-ALU-16": (560, 190), "RM-WHL-ALU-17": (500, 170),
    "RM-WHL-ALU-18": (320, 110), "RM-TYR-15": (180, 60), "RM-TYR-16": (560, 190), "RM-TYR-17": (240, 80),
    "RM-TYR-18": (320, 110), "RM-TYR-17LT": (270, 90), "RM-WHL-HW": (320, 110),

    # ---- purchased: cockpit, HVAC & infotainment ----
    "RM-DSH-B": (70, 25), "RM-DSH-M": (150, 50), "RM-DSH-P": (110, 40), "RM-CLS-ANA": (70, 25),
    "RM-CLS-TFT": (160, 55), "RM-CLS-TFT12": (110, 40), "RM-HDU-7": (70, 25), "RM-HDU-9": (160, 55),
    "RM-HDU-12": (110, 40), "RM-STW-STD": (70, 25), "RM-STW-PRM": (270, 95), "RM-ARB-PAS": (330, 110),
    "RM-ARB-KNEE": (260, 90), "RM-PED-SET": (330, 110), "RM-AUD-6": (230, 80), "RM-AUD-8": (110, 40),
    "RM-TRM-SET": (330, 110), "RM-HVC-CSE-M": (70, 25), "RM-HVC-CSE-A": (270, 95), "RM-BLW-MTR": (330, 110),
    "RM-EVP-CORE": (330, 110), "RM-CND-AC": (330, 110), "RM-ACC-MECH": (210, 75), "RM-ACC-ELE": (115, 40),
    "RM-HVC-CTL": (270, 95), "RM-PTC-HTR": (115, 40),

    # ---- purchased: seating ----
    "RM-SFR-FM": (170, 60), "RM-SFR-FP": (150, 50), "RM-SFR-R": (300, 100), "RM-SFR-3R": (90, 30),
    "RM-SFR-VAN": (32, 12), "RM-FOM-SEAT": (900, 300), "RM-COV-FAB": (520, 180), "RM-COV-LTH": (700, 240),
    "RM-COV-VNL-VAN": (32, 12), "RM-SHT-HEAT": (170, 60), "RM-SBT-SET": (330, 110),

    # ---- purchased: electrical & electronics ----
    "RM-HRN-BDY-S": (220, 75), "RM-HRN-BDY-P": (260, 90), "RM-HRN-DOR": (480, 160), "RM-HRN-ENG": (380, 130),
    "RM-HRN-HV-HEV": (115, 40), "RM-HRN-HV-EV": (140, 50), "RM-BAT-12V-PB": (240, 85), "RM-BAT-12V-LI": (250, 90),
    "RM-ALT-STD": (240, 85), "RM-STM-STD": (360, 120), "RM-BCM-STD": (500, 170), "RM-FSB-SET": (500, 170),
    "RM-SNS-PRK": (3400, 1100), "RM-CAM-RVW": (330, 110), "RM-CAM-360": (270, 95), "RM-KEY-IMM": (500, 170),
    "RM-KEY-SMT": (800, 280), "RM-TCU-TEL": (430, 150), "RM-DCDC-HV": (250, 90), "RM-AVAS": (140, 50),
    "RM-CAM-FRT": (270, 95), "RM-RDR-FRT": (270, 95), "RM-RDR-CRN": (700, 240), "RM-DMS-CAM": (150, 50),
    "RM-ADC-L1": (120, 40), "RM-ADC-L2": (150, 50),

    # ---- SokratesCar: low raw stock on purpose -> shortages trigger purchase proposals to PT Fandi / PT Chris ----
    "FG-SDN-SKR-21": (0, 3),
    "SA-SKR-PWR": (0, 0), "SA-SKR-ENG": (0, 0), "SA-SKR-BODY": (0, 0), "SA-SKR-CHS": (0, 0),
    "SA-SKR-INT": (0, 0), "SA-SKR-ELE": (0, 0),
    "RM-SKR-TRN": (2, 2), "RM-SKR-ECU": (2, 2), "RM-SKR-EXH": (2, 2), "RM-SKR-RAD": (2, 2), "RM-SKR-FTK": (2, 2),
    "RM-SKR-BLK": (2, 2), "RM-SKR-HED": (2, 2), "RM-SKR-INJ": (8, 8), "RM-SKR-SPK": (8, 8), "RM-SKR-OIL": (20, 10),
    "RM-SKR-BSH": (1, 2), "RM-SKR-DRS": (1, 2), "RM-SKR-BMP": (2, 2), "RM-SKR-GLZ": (1, 2), "RM-SKR-PNT": (30, 15),
    "RM-SKR-SUSF": (2, 2), "RM-SKR-SUSR": (2, 2), "RM-SKR-BRK": (2, 2), "RM-SKR-STR": (2, 2), "RM-SKR-WHL": (2, 2),
    "RM-SKR-DSH": (1, 2), "RM-SKR-SEAT": (1, 2), "RM-SKR-HVC": (2, 2), "RM-SKR-HDU": (2, 2), "RM-SKR-TRM": (1, 2),
    "RM-SKR-HRN": (1, 2), "RM-SKR-BAT12": (3, 2), "RM-SKR-BCM": (2, 2), "RM-SKR-ALT": (2, 2), "RM-SKR-STM": (2, 2),
    "RM-SKR-LGT": (1, 2),
}

# sku: [(supplier code, unit price Rp per UOM, lead time days, moq)]
# First entry = preferred vendor. Single-source entries reflect dedicated tooling or sole-qualified suppliers.
SOURCING = {
    # ---- engine & fluids ----
    "RM-BLK-G12": [("SUP-JBC", 4_800_000, 7, 20), ("SUP-NPC", 5_050_000, 5, 10)],
    "RM-HED-G12": [("SUP-JBC", 3_900_000, 7, 20), ("SUP-NPC", 4_100_000, 5, 10)],
    "RM-BLK-G15": [("SUP-JBC", 6_200_000, 7, 20), ("SUP-NPC", 6_450_000, 5, 10)],
    "RM-HED-G15": [("SUP-JBC", 5_100_000, 7, 20), ("SUP-NPC", 5_300_000, 5, 10)],
    "RM-BLK-G20T": [("SUP-JBC", 11_500_000, 10, 10), ("SUP-NPC", 11_950_000, 8, 10)],
    "RM-HED-G20T": [("SUP-JBC", 9_800_000, 10, 10), ("SUP-NPC", 10_150_000, 8, 10)],
    "RM-BLK-D24": [("SUP-JBC", 14_500_000, 12, 10)],
    "RM-HED-D24": [("SUP-JBC", 12_300_000, 12, 10)],
    "RM-BLK-H15": [("SUP-JBC", 6_900_000, 7, 20), ("SUP-NPC", 7_150_000, 5, 10)],
    "RM-HED-H15": [("SUP-JBC", 5_700_000, 7, 20), ("SUP-NPC", 5_900_000, 5, 10)],
    "RM-BLK-H20": [("SUP-JBC", 10_800_000, 10, 10), ("SUP-NPC", 11_200_000, 8, 10)],
    "RM-HED-H20": [("SUP-JBC", 9_200_000, 10, 10), ("SUP-NPC", 9_550_000, 8, 10)],
    "RM-TRB-G20T": [("SUP-TRQ", 7_800_000, 35, 20), ("SUP-BRT", 8_150_000, 28, 20)],
    "RM-TRB-D24": [("SUP-TRQ", 9_500_000, 35, 20), ("SUP-BRT", 9_900_000, 28, 20)],
    "RM-INJ-PFI": [("SUP-DNK", 430_000, 30, 100), ("SUP-BRT", 450_000, 28, 100), ("SUP-NPC", 480_000, 7, 50)],
    "RM-INJ-GDI": [("SUP-DNK", 1_190_000, 30, 100), ("SUP-BRT", 1_250_000, 28, 100)],
    "RM-INJ-CRD": [("SUP-BRT", 2_400_000, 28, 100), ("SUP-DNK", 2_550_000, 30, 100)],
    "RM-SPK-IRI": [("SUP-DNK", 185_000, 30, 200), ("SUP-BRT", 195_000, 28, 200), ("SUP-NPC", 210_000, 5, 100)],
    "RM-GLP-DSL": [("SUP-BRT", 210_000, 28, 100), ("SUP-NPC", 235_000, 6, 100)],
    "RM-CHN-TIM": [("SUP-NPC", 1_350_000, 5, 20), ("SUP-AIS", 1_290_000, 30, 50)],
    "RM-OWP-SET": [("SUP-NPC", 2_100_000, 5, 20), ("SUP-AIS", 2_050_000, 30, 50)],
    "RM-ENM-SET": [("SUP-NPC", 1_650_000, 5, 20), ("SUP-TCS", 1_580_000, 21, 30)],
    "RM-HPF-CRD": [("SUP-BRT", 6_500_000, 28, 20)],
    "RM-EGR-DSL": [("SUP-BRT", 3_200_000, 28, 20), ("SUP-VLR", 3_350_000, 30, 20)],
    "RM-ECU-ENG-G": [("SUP-DNK", 3_750_000, 30, 50), ("SUP-BRT", 3_900_000, 28, 50)],
    "RM-ECU-ENG-D": [("SUP-BRT", 5_200_000, 28, 50)],
    "RM-EOL-5W30": [("SUP-NPC", 95_000, 3, 200), ("SUP-SPR", 98_000, 3, 200)],

    # ---- transmission, driveline & e-drive ----
    "RM-TAX-CVT": [("SUP-AIS", 17_500_000, 35, 20), ("SUP-ZFT", 18_300_000, 42, 20)],
    "RM-TQC-CVT": [("SUP-AIS", 3_650_000, 35, 50), ("SUP-ZFT", 3_800_000, 35, 50)],
    "RM-TAX-AT8": [("SUP-ZFT", 28_500_000, 42, 20)],
    "RM-TQC-AT8": [("SUP-ZFT", 6_900_000, 42, 20)],
    "RM-TAX-AT6": [("SUP-AIS", 21_000_000, 35, 20), ("SUP-ZFT", 22_400_000, 42, 20)],
    "RM-TQC-AT6": [("SUP-AIS", 5_200_000, 35, 50), ("SUP-ZFT", 5_450_000, 42, 50)],
    "RM-TAX-MT6": [("SUP-AIS", 12_500_000, 35, 20), ("SUP-ZFT", 13_200_000, 42, 20)],
    "RM-CLU-MT6": [("SUP-AIS", 3_300_000, 35, 50), ("SUP-ZFT", 3_400_000, 35, 50)],
    "RM-TAX-EVA": [("SUP-AIS", 14_800_000, 40, 20)],
    "RM-TAX-EVB": [("SUP-AIS", 19_500_000, 40, 20)],
    "RM-ATF-FLD": [("SUP-NPC", 110_000, 3, 200), ("SUP-SPR", 118_000, 3, 100)],
    "RM-TFC-AWD": [("SUP-TCS", 9_100_000, 25, 10), ("SUP-ZFT", 9_800_000, 42, 10)],
    "RM-MTR-60": [("SUP-DNK", 11_000_000, 40, 20), ("SUP-MGN", 11_600_000, 45, 20)],
    "RM-MTR-90": [("SUP-SHC", 14_200_000, 50, 20), ("SUP-DNK", 15_500_000, 40, 20)],
    "RM-MTR-150": [("SUP-SHC", 21_800_000, 55, 50), ("SUP-MGN", 24_000_000, 45, 20), ("SUP-DNK", 25_200_000, 40, 20)],
    "RM-MTR-200": [("SUP-SHC", 28_900_000, 55, 50), ("SUP-MGN", 31_000_000, 45, 20)],
    "RM-INV-HYB": [("SUP-DNK", 8_200_000, 40, 20), ("SUP-BRT", 8_700_000, 35, 20)],
    "RM-INV-EV": [("SUP-SHC", 13_200_000, 55, 50), ("SUP-DNK", 14_500_000, 40, 20), ("SUP-BRT", 15_100_000, 35, 20)],
    "RM-RDG-S": [("SUP-AIS", 6_800_000, 35, 20), ("SUP-MGN", 7_100_000, 40, 20)],
    "RM-RDG-L": [("SUP-AIS", 9_400_000, 35, 20), ("SUP-MGN", 9_900_000, 40, 20)],

    # ---- powertrain-level auxiliaries ----
    "RM-ECU-HCU": [("SUP-DNK", 4_600_000, 30, 50), ("SUP-BRT", 4_850_000, 28, 50)],
    "RM-ECU-VCU": [("SUP-DNK", 5_600_000, 30, 50), ("SUP-BRT", 5_800_000, 28, 50)],
    "RM-EXH-GAS": [("SUP-CAT", 5_400_000, 30, 50), ("SUP-NPC", 5_750_000, 7, 20)],
    "RM-EXH-DSL": [("SUP-CAT", 11_800_000, 30, 50)],
    "RM-RAD-S": [("SUP-VLR", 1_450_000, 30, 50), ("SUP-NPC", 1_520_000, 5, 20)],
    "RM-RAD-L": [("SUP-VLR", 2_350_000, 30, 50), ("SUP-NPC", 2_480_000, 5, 20)],
    "RM-FTK-S": [("SUP-IPL", 1_150_000, 5, 50), ("SUP-NPC", 1_220_000, 5, 50)],
    "RM-FTK-L": [("SUP-IPL", 1_750_000, 5, 50)],
    "RM-DEF-TNK": [("SUP-IPL", 2_600_000, 7, 50), ("SUP-CAT", 2_750_000, 30, 50)],
    "RM-TMS-EV": [("SUP-VLR", 7_200_000, 30, 20), ("SUP-DNK", 7_500_000, 35, 20)],

    # ---- battery systems & charging ----
    "RM-CEL-LFP": [("SUP-SPC", 390_000, 30, 1200), ("SUP-ZHB", 405_000, 30, 1200)],
    "RM-CEL-NMC": [("SUP-ZHB", 385_000, 30, 1200), ("SUP-LGX", 410_000, 35, 1200)],
    "RM-CEL-HEV": [("SUP-PNS", 42_000, 40, 5000)],
    "RM-BUS-MOD": [("SUP-ZHB", 495_000, 30, 500), ("SUP-ELX", 520_000, 28, 200)],
    "RM-CSC-MOD": [("SUP-DNK", 680_000, 30, 200), ("SUP-ELX", 705_000, 28, 200)],
    "RM-TIM-PAD": [("SUP-SPR", 138_000, 7, 100), ("SUP-ELX", 150_000, 28, 200)],
    "RM-BMS-HEV": [("SUP-DNK", 3_100_000, 30, 50)],
    "RM-BMS-EV": [("SUP-ZHB", 7_900_000, 35, 100), ("SUP-DNK", 8_500_000, 30, 50), ("SUP-ELX", 8_900_000, 28, 50)],
    "RM-ENC-HEV": [("SUP-GAM", 1_900_000, 10, 50), ("SUP-IPL", 2_000_000, 7, 50)],
    "RM-ENC-PHEV": [("SUP-ZHB", 4_500_000, 30, 50), ("SUP-GAM", 4_800_000, 10, 20)],
    "RM-ENC-EVS": [("SUP-ZHB", 10_800_000, 30, 50), ("SUP-GAM", 11_500_000, 12, 20)],
    "RM-ENC-EVL": [("SUP-ZHB", 14_600_000, 30, 50), ("SUP-GAM", 15_500_000, 12, 20)],
    "RM-CLP-EV": [("SUP-VLR", 1_250_000, 30, 100), ("SUP-GAM", 1_320_000, 10, 50)],
    "RM-HVJ-EV": [("SUP-ELX", 6_400_000, 28, 20), ("SUP-DNK", 6_700_000, 30, 20)],
    "RM-MSD-HV": [("SUP-ELX", 780_000, 28, 100), ("SUP-DNK", 820_000, 30, 100)],
    "RM-OBC-37": [("SUP-ELX", 4_200_000, 28, 20), ("SUP-DNK", 4_400_000, 30, 20)],
    "RM-OBC-110": [("SUP-SHC", 9_100_000, 50, 50), ("SUP-ELX", 9_800_000, 28, 20), ("SUP-DNK", 10_300_000, 30, 20)],
    "RM-INL-T2": [("SUP-ELX", 1_100_000, 28, 50)],
    "RM-INL-CCS2": [("SUP-SHC", 2_650_000, 45, 100), ("SUP-ELX", 2_900_000, 28, 50)],
    "RM-CBL-EVSE": [("SUP-SHC", 1_700_000, 45, 100), ("SUP-ELX", 1_850_000, 28, 50)],

    # ---- body, paint & closures (shells are single-sourced: dedicated stamping dies) ----
    "RM-BSH-HB": [("SUP-GAM", 9_500_000, 10, 20)],
    "RM-BSH-SDN": [("SUP-GAM", 11_200_000, 10, 20)],
    "RM-BSH-SUVC": [("SUP-GAM", 13_800_000, 10, 20)],
    "RM-BSH-SUVM": [("SUP-GAM", 17_500_000, 10, 20)],
    "RM-BSH-MPV": [("SUP-GAM", 16_800_000, 10, 20)],
    "RM-BSH-PKP": [("SUP-GAM", 18_500_000, 10, 20)],
    "RM-BSH-VAN": [("SUP-GAM", 15_900_000, 10, 20)],
    "RM-DRS-C": [("SUP-GAM", 6_500_000, 10, 20), ("SUP-TCS", 6_250_000, 21, 30)],
    "RM-DRS-L": [("SUP-GAM", 9_800_000, 10, 20), ("SUP-TCS", 9_400_000, 21, 30)],
    "RM-BMP-S": [("SUP-IPL", 2_900_000, 5, 50), ("SUP-TCS", 2_780_000, 21, 50)],
    "RM-BMP-L": [("SUP-IPL", 4_600_000, 5, 50), ("SUP-TCS", 4_400_000, 21, 50)],
    "RM-HLP-LED": [("SUP-TLM", 3_800_000, 7, 50), ("SUP-DNK", 4_100_000, 30, 100)],
    "RM-TLP-LED": [("SUP-TLM", 2_100_000, 7, 50), ("SUP-DNK", 2_250_000, 30, 100)],
    "RM-GLZ-S": [("SUP-SGS", 4_200_000, 6, 50)],
    "RM-GLZ-L": [("SUP-SGS", 6_900_000, 6, 50)],
    "RM-MIR-STD": [("SUP-TLM", 1_350_000, 7, 50), ("SUP-DNK", 1_450_000, 30, 100)],
    "RM-PNT-BSC": [("SUP-SPR", 185_000, 4, 100)],
    "RM-PNT-CLR": [("SUP-SPR", 140_000, 4, 100)],
    "RM-CGB-PKP": [("SUP-GAM", 5_400_000, 10, 20)],
    "RM-SLD-VAN": [("SUP-GAM", 7_800_000, 10, 20), ("SUP-TCS", 7_450_000, 21, 20)],

    # ---- suspension, brakes, steering, frames ----
    "RM-STR-FRT": [("SUP-MBR", 2_800_000, 6, 50), ("SUP-TCS", 2_650_000, 21, 100)],
    "RM-LCA-FRT": [("SUP-MBR", 1_150_000, 6, 50), ("SUP-TCS", 1_090_000, 21, 100)],
    "RM-KNK-FRT": [("SUP-JBC", 1_600_000, 8, 50), ("SUP-MBR", 1_680_000, 6, 50)],
    "RM-SUB-FRT": [("SUP-GAM", 3_400_000, 10, 20), ("SUP-MBR", 3_550_000, 6, 20)],
    "RM-TBA-RR": [("SUP-MBR", 3_200_000, 6, 50), ("SUP-TCS", 3_050_000, 21, 100)],
    "RM-MLA-RR": [("SUP-TCS", 8_500_000, 21, 50), ("SUP-MBR", 8_950_000, 8, 20)],
    "RM-RAX-RR": [("SUP-TCS", 6_900_000, 21, 50), ("SUP-MBR", 7_200_000, 8, 20)],
    "RM-LSP-RR": [("SUP-TCS", 1_800_000, 21, 100), ("SUP-MBR", 1_900_000, 6, 50)],
    "RM-SPD-RR": [("SUP-TCS", 2_450_000, 21, 100), ("SUP-MBR", 2_600_000, 6, 50)],
    "RM-DMP-RR": [("SUP-TCS", 1_280_000, 21, 100), ("SUP-MBR", 1_350_000, 6, 50)],
    "RM-BFR-C": [("SUP-MBR", 2_900_000, 6, 50), ("SUP-BRT", 3_250_000, 28, 100)],
    "RM-BRR-C": [("SUP-MBR", 1_700_000, 6, 50), ("SUP-BRT", 1_900_000, 28, 100)],
    "RM-BFR-H": [("SUP-MBR", 4_300_000, 6, 50), ("SUP-BRT", 4_700_000, 28, 100)],
    "RM-BRR-H": [("SUP-MBR", 2_600_000, 6, 50), ("SUP-BRT", 2_850_000, 28, 100)],
    "RM-ABS-ESC": [("SUP-DNK", 6_550_000, 30, 50), ("SUP-BRT", 6_800_000, 28, 50)],
    "RM-ABS-WSS": [("SUP-DNK", 295_000, 30, 200), ("SUP-BRT", 320_000, 28, 200)],
    "RM-BMC-STD": [("SUP-MBR", 2_400_000, 6, 50), ("SUP-BRT", 2_650_000, 28, 100)],
    "RM-EPB-ACT": [("SUP-MKT", 1_020_000, 25, 100), ("SUP-BRT", 1_100_000, 28, 100)],
    "RM-BRF-DOT4": [("SUP-SPR", 95_000, 4, 100), ("SUP-NPC", 99_000, 3, 100)],
    "RM-RCK-EPS": [("SUP-MKT", 4_600_000, 25, 50), ("SUP-BRT", 4_950_000, 28, 50)],
    "RM-EPM-EPS": [("SUP-MKT", 2_100_000, 25, 50), ("SUP-DNK", 2_250_000, 30, 50)],
    "RM-STC-STD": [("SUP-MKT", 950_000, 25, 100), ("SUP-MBR", 1_010_000, 6, 50)],
    "RM-LDR-FRM": [("SUP-GAM", 14_500_000, 12, 20)],
    "RM-UBF-VAN": [("SUP-GAM", 9_800_000, 12, 20)],

    # ---- wheels & tyres ----
    "RM-WHL-ALU-15": [("SUP-WLS", 650_000, 6, 100)],
    "RM-WHL-ALU-16": [("SUP-WLS", 850_000, 6, 100)],
    "RM-WHL-ALU-17": [("SUP-WLS", 1_100_000, 6, 100), ("SUP-GAM", 1_160_000, 8, 100)],
    "RM-WHL-ALU-18": [("SUP-WLS", 1_450_000, 6, 100), ("SUP-GAM", 1_520_000, 8, 100)],
    "RM-TYR-15": [("SUP-HYT", 610_000, 30, 200), ("SUP-BWY", 650_000, 25, 200)],
    "RM-TYR-16": [("SUP-HYT", 800_000, 30, 200), ("SUP-BWY", 850_000, 25, 200)],
    "RM-TYR-17": [("SUP-HYT", 990_000, 30, 200), ("SUP-BWY", 1_050_000, 25, 200)],
    "RM-TYR-18": [("SUP-HYT", 1_420_000, 30, 200), ("SUP-BWY", 1_500_000, 25, 200)],
    "RM-TYR-17LT": [("SUP-HYT", 1_560_000, 30, 200), ("SUP-BWY", 1_650_000, 25, 200)],
    "RM-WHL-HW": [("SUP-WLS", 480_000, 6, 200), ("SUP-DNK", 520_000, 30, 200)],

    # ---- cockpit, HVAC & infotainment ----
    "RM-DSH-B": [("SUP-IPL", 3_200_000, 6, 50)],
    "RM-DSH-M": [("SUP-IPL", 5_400_000, 6, 50)],
    "RM-DSH-P": [("SUP-IPL", 9_800_000, 8, 30)],
    "RM-CLS-ANA": [("SUP-SND", 1_100_000, 30, 100), ("SUP-DNK", 1_180_000, 30, 100)],
    "RM-CLS-TFT": [("SUP-SND", 3_200_000, 30, 100), ("SUP-DNK", 3_450_000, 30, 100)],
    "RM-CLS-TFT12": [("SUP-SND", 5_600_000, 30, 50), ("SUP-DNK", 5_900_000, 30, 50)],
    "RM-HDU-7": [("SUP-SND", 1_900_000, 30, 100)],
    "RM-HDU-9": [("SUP-SND", 3_400_000, 30, 100), ("SUP-DNK", 3_600_000, 30, 100)],
    "RM-HDU-12": [("SUP-SND", 7_800_000, 30, 50)],
    "RM-STW-STD": [("SUP-IPL", 1_280_000, 7, 100), ("SUP-AXL", 1_350_000, 30, 100)],
    "RM-STW-PRM": [("SUP-AXL", 3_100_000, 30, 50)],
    "RM-ARB-PAS": [("SUP-AXL", 1_650_000, 30, 100), ("SUP-BRT", 1_720_000, 28, 100)],
    "RM-ARB-KNEE": [("SUP-AXL", 1_200_000, 30, 100)],
    "RM-PED-SET": [("SUP-MKT", 780_000, 25, 100), ("SUP-MBR", 820_000, 6, 50)],
    "RM-AUD-6": [("SUP-SND", 1_800_000, 30, 100)],
    "RM-AUD-8": [("SUP-SND", 6_200_000, 30, 50)],
    "RM-TRM-SET": [("SUP-IPL", 4_800_000, 7, 50), ("SUP-PTN", 5_050_000, 7, 30)],
    "RM-HVC-CSE-M": [("SUP-VLR", 1_100_000, 30, 50), ("SUP-IPL", 1_180_000, 7, 50)],
    "RM-HVC-CSE-A": [("SUP-VLR", 1_900_000, 30, 50), ("SUP-IPL", 1_980_000, 7, 50)],
    "RM-BLW-MTR": [("SUP-DNK", 620_000, 30, 100), ("SUP-VLR", 650_000, 30, 100)],
    "RM-EVP-CORE": [("SUP-VLR", 900_000, 30, 100)],
    "RM-CND-AC": [("SUP-VLR", 850_000, 30, 100), ("SUP-NPC", 900_000, 5, 50)],
    "RM-ACC-MECH": [("SUP-DNK", 2_780_000, 30, 50), ("SUP-VLR", 2_900_000, 30, 50)],
    "RM-ACC-ELE": [("SUP-DNK", 6_600_000, 30, 50), ("SUP-VLR", 6_900_000, 30, 50)],
    "RM-HVC-CTL": [("SUP-DNK", 1_300_000, 30, 100), ("SUP-VLR", 1_380_000, 30, 100)],
    "RM-PTC-HTR": [("SUP-VLR", 2_200_000, 30, 50)],

    # ---- seating ----
    "RM-SFR-FM": [("SUP-BDG", 2_400_000, 6, 50), ("SUP-AXL", 2_650_000, 30, 100)],
    "RM-SFR-FP": [("SUP-BDG", 5_600_000, 8, 30), ("SUP-AXL", 5_950_000, 30, 50)],
    "RM-SFR-R": [("SUP-BDG", 1_900_000, 6, 50)],
    "RM-SFR-3R": [("SUP-BDG", 1_700_000, 6, 50)],
    "RM-SFR-VAN": [("SUP-BDG", 2_100_000, 6, 50)],
    "RM-FOM-SEAT": [("SUP-IPL", 545_000, 5, 100), ("SUP-BDG", 520_000, 6, 100)],
    "RM-COV-FAB": [("SUP-PTN", 650_000, 5, 100), ("SUP-BDG", 690_000, 6, 100)],
    "RM-COV-LTH": [("SUP-PTN", 1_850_000, 7, 50)],
    "RM-COV-VNL-VAN": [("SUP-PTN", 480_000, 5, 100)],
    "RM-SHT-HEAT": [("SUP-BDG", 550_000, 8, 100), ("SUP-AXL", 590_000, 30, 100)],
    "RM-SBT-SET": [("SUP-AXL", 2_600_000, 30, 100)],

    # ---- electrical & electronics ----
    "RM-HRN-BDY-S": [("SUP-VHM", 3_150_000, 21, 100), ("SUP-CWH", 3_400_000, 7, 50)],
    "RM-HRN-BDY-P": [("SUP-VHM", 4_850_000, 21, 100), ("SUP-CWH", 5_200_000, 7, 50)],
    "RM-HRN-DOR": [("SUP-VHM", 1_210_000, 21, 200), ("SUP-CWH", 1_300_000, 7, 100)],
    "RM-HRN-ENG": [("SUP-VHM", 1_790_000, 21, 100), ("SUP-CWH", 1_900_000, 7, 50)],
    "RM-HRN-HV-HEV": [("SUP-CWH", 2_800_000, 8, 50), ("SUP-ELX", 3_050_000, 28, 50)],
    "RM-HRN-HV-EV": [("SUP-VHM", 5_800_000, 21, 50), ("SUP-CWH", 6_100_000, 10, 20), ("SUP-ELX", 6_400_000, 28, 20)],
    "RM-BAT-12V-PB": [("SUP-DNK", 1_100_000, 30, 200), ("SUP-NPC", 1_150_000, 5, 100)],
    "RM-BAT-12V-LI": [("SUP-LGX", 3_250_000, 35, 100), ("SUP-DNK", 3_400_000, 30, 100)],
    "RM-ALT-STD": [("SUP-DNK", 1_850_000, 30, 100), ("SUP-NPC", 1_950_000, 5, 50)],
    "RM-STM-STD": [("SUP-DNK", 1_250_000, 30, 100), ("SUP-NPC", 1_320_000, 5, 50)],
    "RM-BCM-STD": [("SUP-DNK", 1_540_000, 30, 100), ("SUP-BRT", 1_600_000, 28, 100)],
    "RM-FSB-SET": [("SUP-VHM", 485_000, 21, 200), ("SUP-CWH", 520_000, 6, 100)],
    "RM-SNS-PRK": [("SUP-DNK", 145_000, 30, 400), ("SUP-BRT", 152_000, 28, 400)],
    "RM-CAM-RVW": [("SUP-SND", 745_000, 30, 100), ("SUP-DNK", 780_000, 30, 100)],
    "RM-CAM-360": [("SUP-DNK", 3_600_000, 30, 50), ("SUP-ADV", 3_900_000, 30, 50)],
    "RM-KEY-IMM": [("SUP-VHM", 330_000, 21, 400), ("SUP-DNK", 350_000, 30, 200)],
    "RM-KEY-SMT": [("SUP-DNK", 1_100_000, 30, 100), ("SUP-BRT", 1_180_000, 28, 100)],
    "RM-TCU-TEL": [("SUP-SND", 1_950_000, 30, 100), ("SUP-DNK", 2_050_000, 30, 100)],
    "RM-DCDC-HV": [("SUP-DNK", 3_300_000, 30, 50), ("SUP-ELX", 3_500_000, 28, 50)],
    "RM-AVAS": [("SUP-SND", 455_000, 30, 200), ("SUP-DNK", 480_000, 30, 200)],
    "RM-CAM-FRT": [("SUP-DNK", 2_450_000, 30, 100), ("SUP-ADV", 2_600_000, 28, 100)],
    "RM-RDR-FRT": [("SUP-ADV", 2_900_000, 28, 100), ("SUP-BRT", 3_100_000, 28, 100)],
    "RM-RDR-CRN": [("SUP-ADV", 1_250_000, 28, 200), ("SUP-BRT", 1_320_000, 28, 200)],
    "RM-DMS-CAM": [("SUP-ADV", 950_000, 28, 100)],
    "RM-ADC-L1": [("SUP-ADV", 3_100_000, 28, 50), ("SUP-BRT", 3_250_000, 28, 50)],
    "RM-ADC-L2": [("SUP-ADV", 9_800_000, 28, 50)],

    # ---- SokratesCar: ONLY PT Fandi (SUP-FND) and PT Chris (SUP-CHR) ----
    "RM-SKR-TRN": [("SUP-FND", 17_200_000, 4, 1), ("SUP-CHR", 17_900_000, 5, 1)],
    "RM-SKR-ECU": [("SUP-CHR", 3_650_000, 4, 1), ("SUP-FND", 3_800_000, 3, 1)],
    "RM-SKR-EXH": [("SUP-FND", 5_300_000, 4, 1), ("SUP-CHR", 5_500_000, 5, 1)],
    "RM-SKR-RAD": [("SUP-CHR", 1_460_000, 5, 1), ("SUP-FND", 1_400_000, 3, 1)],
    "RM-SKR-FTK": [("SUP-FND", 1_100_000, 3, 1), ("SUP-CHR", 1_150_000, 4, 1)],
    "RM-SKR-BLK": [("SUP-CHR", 6_250_000, 6, 1), ("SUP-FND", 6_000_000, 5, 1)],
    "RM-SKR-HED": [("SUP-FND", 5_000_000, 5, 1), ("SUP-CHR", 5_150_000, 6, 1)],
    "RM-SKR-INJ": [("SUP-CHR", 455_000, 4, 8), ("SUP-FND", 440_000, 3, 8)],
    "RM-SKR-SPK": [("SUP-FND", 190_000, 3, 8), ("SUP-CHR", 185_000, 4, 8)],
    "RM-SKR-OIL": [("SUP-CHR", 97_000, 3, 20), ("SUP-FND", 94_000, 3, 20)],
    "RM-SKR-BSH": [("SUP-FND", 11_000_000, 7, 1), ("SUP-CHR", 11_400_000, 7, 1)],
    "RM-SKR-DRS": [("SUP-CHR", 6_300_000, 6, 1), ("SUP-FND", 6_400_000, 5, 1)],
    "RM-SKR-BMP": [("SUP-FND", 2_850_000, 4, 1), ("SUP-CHR", 2_950_000, 5, 1)],
    "RM-SKR-GLZ": [("SUP-CHR", 4_250_000, 5, 1), ("SUP-FND", 4_100_000, 4, 1)],
    "RM-SKR-PNT": [("SUP-FND", 160_000, 3, 20), ("SUP-CHR", 165_000, 4, 20)],
    "RM-SKR-SUSF": [("SUP-CHR", 5_400_000, 5, 1), ("SUP-FND", 5_200_000, 4, 1)],
    "RM-SKR-SUSR": [("SUP-FND", 4_100_000, 4, 1), ("SUP-CHR", 4_000_000, 5, 1)],
    "RM-SKR-BRK": [("SUP-CHR", 4_650_000, 4, 1), ("SUP-FND", 4_500_000, 3, 1)],
    "RM-SKR-STR": [("SUP-FND", 7_300_000, 5, 1), ("SUP-CHR", 7_500_000, 6, 1)],
    "RM-SKR-WHL": [("SUP-CHR", 8_000_000, 4, 1), ("SUP-FND", 8_200_000, 3, 1)],
    "RM-SKR-DSH": [("SUP-FND", 5_300_000, 5, 1), ("SUP-CHR", 5_500_000, 5, 1)],
    "RM-SKR-SEAT": [("SUP-CHR", 11_900_000, 6, 1), ("SUP-FND", 11_500_000, 6, 1)],
    "RM-SKR-HVC": [("SUP-FND", 6_200_000, 4, 1), ("SUP-CHR", 6_050_000, 5, 1)],
    "RM-SKR-HDU": [("SUP-CHR", 3_450_000, 4, 1), ("SUP-FND", 3_300_000, 4, 1)],
    "RM-SKR-TRM": [("SUP-FND", 4_700_000, 5, 1), ("SUP-CHR", 4_850_000, 5, 1)],
    "RM-SKR-HRN": [("SUP-CHR", 8_700_000, 5, 1), ("SUP-FND", 8_400_000, 6, 1)],
    "RM-SKR-BAT12": [("SUP-FND", 1_120_000, 3, 1), ("SUP-CHR", 1_160_000, 3, 1)],
    "RM-SKR-BCM": [("SUP-CHR", 1_500_000, 4, 1), ("SUP-FND", 1_550_000, 4, 1)],
    "RM-SKR-ALT": [("SUP-FND", 1_800_000, 4, 1), ("SUP-CHR", 1_850_000, 4, 1)],
    "RM-SKR-STM": [("SUP-CHR", 1_290_000, 4, 1), ("SUP-FND", 1_240_000, 3, 1)],
    "RM-SKR-LGT": [("SUP-FND", 6_000_000, 5, 1), ("SUP-CHR", 6_200_000, 6, 1)],
}

def validate_seed_data() -> None:
    """Integrity checks on the global tables BEFORE touching the database (fail fast, list all problems)."""
    err: list[str] = []
    cat = {}
    for sku, _name, _uom, c in MATERIALS:
        if sku in cat:
            err.append(f"duplicate SKU in MATERIALS: {sku}")
        cat[sku] = c
    sup_codes = [c for c, _n, _ct in SUPPLIERS]
    if len(sup_codes) != len(set(sup_codes)):
        err.append("duplicate supplier code in SUPPLIERS")
    if len(LINES) != len({c for c, _ in LINES}):
        err.append("duplicate production line code in LINES")
    err += [f"TERMS references unknown supplier {c}" for c in TERMS if c not in sup_codes]

    fg = {s for s, c in cat.items() if c == FIN}
    if len(fg) < 20:
        err.append(f"need >= 20 finished vehicles, found {len(fg)}")
    if set(FINISHED) != fg:
        err.append(f"FINISHED specs mismatch: {sorted(set(FINISHED) ^ fg)}")
    for sku, (price, spec) in FINISHED.items():
        if price <= 0 or len(spec) > 500:
            err.append(f"bad price/spec length for {sku}")

    pairs, children, parents = set(), set(), set()
    graph: dict[str, list[str]] = {}
    for p, c, q in BOM:
        if p not in cat or c not in cat:
            err.append(f"BOM references unknown SKU: {p} -> {c}")
            continue
        if p == c:
            err.append(f"BOM self-reference: {p}")
        if q <= 0:
            err.append(f"BOM non-positive qty: {p} -> {c}")
        if (p, c) in pairs:
            err.append(f"BOM duplicate pair: {p} -> {c}")
        if cat[p] == BUY:
            err.append(f"PURCHASED item cannot be a BOM parent: {p}")
        if cat[c] == FIN:
            err.append(f"FINISHED item cannot be a BOM child: {c}")
        pairs.add((p, c)); children.add(c); parents.add(p)
        graph.setdefault(p, []).append(c)
    err += [f"{s} ({c.name}) has no BOM children" for s, c in cat.items() if c != BUY and s not in parents]
    err += [f"{s} is never used in any BOM" for s, c in cat.items() if c != FIN and s not in children]

    state: dict[str, int] = {}          # 1 = visiting, 2 = done (cycle detection)

    def dfs(node: str) -> None:
        if state.get(node) == 2:
            return
        if state.get(node) == 1:
            err.append(f"BOM cycle detected at {node}")
            return
        state[node] = 1
        for ch in graph.get(node, []):
            dfs(ch)
        state[node] = 2
    for s in fg:
        dfs(s)

    err += [f"missing INVENTORY for {s}" for s in cat if s not in INVENTORY]
    err += [f"INVENTORY has unknown SKU {s}" for s in INVENTORY if s not in cat]
    err += [f"negative inventory for {s}" for s, (oh, ss) in INVENTORY.items() if oh < 0 or ss < 0]

    buy = {s for s, c in cat.items() if c == BUY}
    err += [f"PURCHASED {s} has no SOURCING" for s in sorted(buy - set(SOURCING))]
    err += [f"SOURCING for non-purchased/unknown SKU {s}" for s in sorted(set(SOURCING) - buy)]
    used_sup = set()
    for sku, rows in SOURCING.items():
        codes = [r[0] for r in rows]
        if len(codes) != len(set(codes)):
            err.append(f"duplicate supplier for {sku}")
        for code, price, lead, moq in rows:
            used_sup.add(code)
            if code not in sup_codes:
                err.append(f"SOURCING {sku}: unknown supplier {code}")
            if price < 0 or lead < 0 or moq <= 0:
                err.append(f"SOURCING {sku}/{code}: violates check constraint")
    err += [f"supplier {c} supplies nothing" for c in sup_codes if c not in used_sup]
    skr_raw = {s for s in buy if s.startswith("RM-SKR-")}
    for sku in sorted(skr_raw):
        if {r[0] for r in SOURCING.get(sku, [])} != {"SUP-FND", "SUP-CHR"}:
            err.append(f"{sku}: SokratesCar raw material must be sourced from exactly PT Fandi and PT Chris")
    for sku in sorted(buy - skr_raw):
        if {r[0] for r in SOURCING.get(sku, [])} & {"SUP-FND", "SUP-CHR"}:
            err.append(f"{sku}: PT Fandi / PT Chris must supply SokratesCar raw materials only")
    if err:
        raise ValueError("Seed data validation failed:\n  - " + "\n  - ".join(err))


def seed(db: Session, with_schedules: bool = False) -> dict:
    """Populate the DB with the automotive dataset. Returns key ids for tests/demos."""
    if db.scalar(select(Material.id).limit(1)) is not None:
        raise RuntimeError("Database already contains data. Use --reset to re-seed.")
    validate_seed_data()

    sup = {code: Supplier(code=code, name=name, contact=contact, payment_term_days=TERMS.get(code, 0))
           for code, name, contact in SUPPLIERS}
    lines = {code: ProductionLine(code=code, name=name) for code, name in LINES}
    db.add_all(lines.values())
    mat = {sku: Material(sku=sku, name=name, uom=uom, category=cat)
           for sku, name, uom, cat in MATERIALS}
    for sku, (price, spec) in FINISHED.items():      # selling price & specification: finished vehicles only
        mat[sku].selling_price = price
        mat[sku].specification = spec
    db.add_all([*sup.values(), *mat.values()])
    db.flush()

    db.add_all(BOMItem(parent_id=mat[p].id, child_id=mat[c].id, qty_per_parent=q) for p, c, q in BOM)
    db.add_all(Inventory(material_id=mat[sku].id, on_hand=oh, allocated=0.0, safety_stock=ss)
               for sku, (oh, ss) in INVENTORY.items())
    for sku, rows in SOURCING.items():
        for i, (code, price, lead, moq) in enumerate(rows):
            db.add(MaterialSupplier(material_id=mat[sku].id, supplier_id=sup[code].id,
                                    unit_price=price, lead_time_days=lead, moq=moq,
                                    is_preferred=(i == 0)))
    db.commit()
    if with_schedules:   # via service: batch code + line + allocated calculation
        from app.services import schedule_service
        monday = date.today() + timedelta(days=(-date.today().weekday()) % 7)   # nearest Monday (today if Monday)
        schedule_service.create_schedule(db, mat["FG-SUV-HEV-11"].id, monday, 30, lines["LINE-FA-01"].id)
        schedule_service.create_schedule(db, mat["FG-SUV-BEV-16"].id, monday + timedelta(days=1), 20,
                                         lines["LINE-FA-02"].id)
        schedule_service.create_schedule(db, mat["FG-SDN-SKR-21"].id, monday + timedelta(days=2), 10,
                                         lines["LINE-FA-01"].id)   # SokratesCar -> Telegram test
    return {
        "vehicles": {s: mat[s].id for s in FINISHED},
        "materials": {sku: m.id for sku, m in mat.items()},
        "suppliers": {code: s.id for code, s in sup.items()},
        "lines": {code: ln.id for code, ln in lines.items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed data: automotive MRP & vendor sourcing")
    ap.add_argument("--reset", action="store_true", help="drop & recreate all tables")
    ap.add_argument("--demo-schedules", action="store_true",
                    help="add demo schedules (nearest Monday): 30 x FG-SUV-HEV-11, Tuesday 20 x FG-SUV-BEV-16, Wednesday 10 x SokratesCar")
    args = ap.parse_args()
    if args.reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        ids = seed(db, with_schedules=args.demo_schedules)
    if TG_FANDI.startswith("ISI_") or TG_CHRIS.startswith("ISI_"):
        print("WARNING: Telegram chat_id for PT Fandi / PT Chris not set. Export TELEGRAM_CHAT_ID_FANDI and "
              "TELEGRAM_CHAT_ID_CHRIS before seeding (or update Supplier.contact later).")
    print(f"Seed complete: {len(ids['materials'])} materials ({len(ids['vehicles'])} vehicles), "
          f"{len(ids['suppliers'])} suppliers, {len(ids['lines'])} production lines, "
          f"{len(BOM)} BOM rows, {sum(len(v) for v in SOURCING.values())} sourcing rows.")


if __name__ == "__main__":
    main()