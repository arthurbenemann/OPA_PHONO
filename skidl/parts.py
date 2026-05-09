"""SKiDL part templates for the OPA_PHONO project.

These mirror the symbols in PCB/OPA_PHONO.kicad_sym so the design can
generate a netlist without depending on the .kicad_sym file or external
library search paths.

Pin numbers and names match the .kicad_sym exactly.  Generic op-amp /
resistor / capacitor parts still come from SKiDL's bundled libraries
(Device, Mechanical) -- only the project-specific custom symbols are
defined here.

To use:
    from parts import OPA1644, OPA1612, LTC3265, RCA_DUAL, USBC, HOUSING
    u1 = OPA1644(ref='U1', footprint='Package_SO:SOIC-14_3.9x8.7mm_P1.27mm')
    u1[4]  += VP            # V+
    u1[11] += VN            # V-
    u1[3]  += sig_in        # +IN_A
"""

from skidl import Part, Pin, TEMPLATE

# Convenience: short aliases for pin function types.
_IN  = Pin.types.INPUT
_OUT = Pin.types.OUTPUT
_PWR = Pin.types.PWRIN
_PSV = Pin.types.PASSIVE
_BID = Pin.types.BIDIR


# ---------------------------------------------------------------- OPA1644

# OPA1644 / OPA1644A: quad audio op-amp, JFET input, SOIC-14 (D package).
# Standard quad op-amp pinout (matches TI OPA164x datasheet & .kicad_sym):
#   V+ = pin 4, V- = pin 11.  Gates A/B on the left side, C/D on the right.
OPA1644 = Part(
    name='OPA1644AxD', ref_prefix='U', dest=TEMPLATE,
    description='Quad audio op-amp, JFET input',
    pins=[
        Pin(num=1,  name='~',  func=_OUT),   # OUT A
        Pin(num=2,  name='-',  func=_IN),    # -IN A
        Pin(num=3,  name='+',  func=_IN),    # +IN A
        Pin(num=4,  name='V+', func=_PWR),
        Pin(num=5,  name='+',  func=_IN),    # +IN B
        Pin(num=6,  name='-',  func=_IN),    # -IN B
        Pin(num=7,  name='~',  func=_OUT),   # OUT B
        Pin(num=8,  name='~',  func=_OUT),   # OUT C
        Pin(num=9,  name='-',  func=_IN),    # -IN C
        Pin(num=10, name='+',  func=_IN),    # +IN C
        Pin(num=11, name='V-', func=_PWR),
        Pin(num=12, name='+',  func=_IN),    # +IN D
        Pin(num=13, name='-',  func=_IN),    # -IN D
        Pin(num=14, name='~',  func=_OUT),   # OUT D
    ],
)


# ---------------------------------------------------------------- OPA1612

# OPA1612A: dual audio op-amp, bipolar input, SOIC-8 (D package).
# Standard dual op-amp pinout: V- = pin 4, V+ = pin 8.
OPA1612 = Part(
    name='OPA1612AxD', ref_prefix='U', dest=TEMPLATE,
    description='Dual audio op-amp, bipolar input',
    pins=[
        Pin(num=1, name='~',  func=_OUT),    # OUT A
        Pin(num=2, name='-',  func=_IN),     # -IN A
        Pin(num=3, name='+',  func=_IN),     # +IN A
        Pin(num=4, name='V-', func=_PWR),
        Pin(num=5, name='+',  func=_IN),     # +IN B
        Pin(num=6, name='-',  func=_IN),     # -IN B
        Pin(num=7, name='~',  func=_OUT),    # OUT B
        Pin(num=8, name='V+', func=_PWR),
    ],
)


# ---------------------------------------------------------------- LTC3265

# LTC3265: dual charge-pump regulator with boost + invert + integrated LDOs.
# DHC-18 package (3x5 mm DFN with exposed pad).  Pin 19 = exposed pad / GND.
#
#   Boost path:  VINP -> CBSTP/CBSTN flying cap -> VOUTP (raw) -> LDOP (out)
#   Invert path: VINN -> CINVP/CINVN flying cap -> VOUTN (raw) -> LDON (out)
#   ADJP / ADJN  : LDO feedback (regulates ADJ to ~1.18V)
#   BYPP / BYPN  : LDO reference bypass cap (low-noise mode)
#   ENP  / ENN   : enable pins for boost / inverter sections
#   RT           : oscillator timing resistor to GND
#   MODE         : forced-PWM vs burst mode select
LTC3265 = Part(
    name='LTC3265xDHC', ref_prefix='U', dest=TEMPLATE,
    description='Dual charge-pump with integrated LDOs',
    pins=[
        Pin(num=1,  name='CBSTN', func=_PSV),
        Pin(num=2,  name='CBSTP', func=_PSV),
        Pin(num=3,  name='VINP',  func=_PSV),
        Pin(num=4,  name='ENN',   func=_PSV),
        Pin(num=5,  name='BYPN',  func=_PSV),
        Pin(num=6,  name='ADJN',  func=_PSV),
        Pin(num=7,  name='LDON',  func=_PSV),
        Pin(num=8,  name='VOUTN', func=_PSV),
        Pin(num=9,  name='CINVN', func=_PSV),
        Pin(num=10, name='CINVP', func=_PSV),
        Pin(num=11, name='VINN',  func=_PSV),
        Pin(num=12, name='RT',    func=_PSV),
        Pin(num=13, name='ENP',   func=_PSV),
        Pin(num=14, name='MODE',  func=_PSV),
        Pin(num=15, name='BYPP',  func=_PSV),
        Pin(num=16, name='ADJP',  func=_PSV),
        Pin(num=17, name='LDOP',  func=_PSV),
        Pin(num=18, name='VOUTP', func=_PSV),
        Pin(num=19, name='GND',   func=_PSV),  # exposed pad
    ],
)


# ---------------------------------------------------------------- RCA jack

# Switchcraft PJRAS2X1S01X: dual stacked mono RCA jack (red/black).
# Pin labels are non-numeric: T1/T2 = top/bottom tip (signal),
# S1/S2 = top/bottom shell (ground).
RCA_DUAL = Part(
    name='PJRAS2X1S01X', ref_prefix='J', dest=TEMPLATE,
    description='Dual mono RCA jack, right-angle SMT',
    pins=[
        Pin(num='T1', name='T1', func=_PSV),
        Pin(num='T2', name='T2', func=_PSV),
        Pin(num='S1', name='S1', func=_PSV),
        Pin(num='S2', name='S2', func=_PSV),
    ],
)


# ---------------------------------------------------------------- USB-C

# CUI UJC-HP-3-SMT-TR: USB 2.0-only Type-C receptacle, right-angle SMT.
# Symmetric pinout (A/B sides) + four shield tabs.  D+/D- are not exposed
# on this part because USB 2.0 lines are unused for a power-only device.
USBC = Part(
    name='UJC-HP-3-SMT-TR', ref_prefix='J', dest=TEMPLATE,
    description='USB 2.0 Type-C receptacle (power-only)',
    pins=[
        Pin(num='A5',  name='CC1',    func=_BID),
        Pin(num='A9',  name='VBUS',   func=_PSV),
        Pin(num='A12', name='GND',    func=_PSV),
        Pin(num='B5',  name='CC2',    func=_BID),
        Pin(num='B9',  name='VBUS',   func=_PSV),
        Pin(num='B12', name='GND',    func=_PSV),
        Pin(num='S1',  name='SHIELD', func=_PSV),
        Pin(num='S2',  name='SHIELD', func=_PSV),
        Pin(num='S3',  name='SHIELD', func=_PSV),
        Pin(num='S4',  name='SHIELD', func=_PSV),
    ],
)


# ---------------------------------------------------------------- Housing

# Hammond 1455L801 enclosure (mechanical-only, no electrical pins).
HOUSING = Part(
    name='Housing', ref_prefix='N', dest=TEMPLATE,
    description='Hammond 1455L extruded aluminium enclosure',
    pins=[],
)
