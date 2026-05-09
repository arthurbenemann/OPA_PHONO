#!/usr/bin/env python3
"""SKiDL representation of the OPA_PHONO USB-C powered MM phono preamp.

Mirrors the KiCad hierarchical schematic in PCB/:

  OPA_PHONO.kicad_sch (top): RCA jacks J1/J2, USB-C J3, CC pulldowns,
    instantiates LEFT, RIGHT (= RIAA_PHONO sheet x2) and POWER.

  RIAA_PHONO.kicad_sch (per channel):
    - Cartridge load: R1=47k to GND, optional C (DNP) for cartridge tuning.
    - Stage 1 (OPA1644 section): non-inverting, gain = 1 + 16k/499 ~= 30 dB.
    - Passive RIAA: R4=16k series; R5=2.32k + C2,C3=68n shunt; C4=47n shunt.
        R5*(C2+C3) = 2.32k * 136n = 315 us, matches the 318 us RIAA constant.
    - Stage 2 (OPA1612 section): non-inverting, gain ~= 30 dB.
    - DC servo (OPA1644 section): integrator with C5=1u and 47k summing
        resistors removes output DC offset without a coupling cap.
    - Output series R12=499R for cap-load isolation / short-circuit limit.

  POWER.kicad_sch:
    - LTC3265: dual charge-pump with boost + invert + integrated LDOs.
    - Generates +/-6V from USB +5V.
    - LDO feedback dividers 20.5k/5.1k, V_ADJ ~= 1.18V => ~5.93V rails.

Per-channel allocation across the two physical chips:

    U1 (OPA1644, quad)   gate A  -> LEFT  stage 1
                         gate B  -> LEFT  DC servo
                         gate C  -> RIGHT stage 1
                         gate D  -> RIGHT DC servo
    U2 (OPA1612, dual)   gate A  -> LEFT  stage 2
                         gate B  -> RIGHT stage 2

NOTE: the gate <-> role mapping above is inferred from sheet-instance unit
numbers and physical position; if a future trace shows it swapped, only
the gate tuples passed to riaa_channel() need to change.

Run:
    pip install skidl
    cd skidl
    python opa_phono.py        # generates opa_phono.net (KiCad netlist)
"""

import os
from skidl import (
    Part, Net, Bus, generate_netlist, set_default_tool, KICAD,
    lib_search_paths, subcircuit, ERC,
)

set_default_tool(KICAD)

# Custom symbols (RCA, USB-C, OPA1644, OPA1612, LTC3265) live in
# PCB/OPA_PHONO.kicad_sym, RCA.kicad_sym.
HERE = os.path.dirname(os.path.abspath(__file__))
lib_search_paths[KICAD].append(os.path.join(HERE, '..', 'PCB'))


# ---------------------------------------------------------------- footprints

FP_R0402  = 'Resistor_SMD:R_0402_1005Metric'
FP_C0402  = 'Capacitor_SMD:C_0402_1005Metric'
FP_C0805  = 'Capacitor_SMD:C_0805_2012Metric'
FP_C1206  = 'Capacitor_SMD:C_1206_3216Metric'
FP_C1210  = 'Capacitor_SMD:C_1210_3225Metric'
FP_SOIC8  = 'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm'
FP_SOIC14 = 'Package_SO:SOIC-14_3.9x8.7mm_P1.27mm'
FP_DFN18  = 'Package_DFN_QFN:DFN-18-1EP_3x5mm_P0.5mm_EP1.66x4.4mm'


def R(value, ref=None, fp=FP_R0402):
    return Part('Device', 'R', value=value, ref=ref, footprint=fp)


def C(value, ref=None, fp=FP_C0402, dnp=False):
    p = Part('Device', 'C', value=value, ref=ref, footprint=fp)
    if dnp:
        p.dnp = True
    return p


def decouple(rail, gnd, value='1u', ref=None, fp=FP_C0402):
    """One bypass cap from rail to gnd."""
    c = C(value, ref=ref, fp=fp)
    c[1] += rail
    c[2] += gnd
    return c


# ---------------------------------------------------------------- POWER sheet

@subcircuit
def power(VIN, VP, VN, GND):
    """LTC3265 dual charge-pump: USB +5V VIN -> +/-6V (VP, VN).

    Boost path: VIN + flying cap on CBSTP/CBSTN -> VOUTP_RAW -> LDO -> VP.
    Invert path: VIN + flying cap on CINVP/CINVN -> VOUTN_RAW -> LDO -> VN.
    Each LDO is set by a feedback divider on ADJP / ADJN to ~6V.
    """
    u3 = Part('OPA_PHONO', 'LTC3265xDHC', ref='U3', footprint=FP_DFN18)

    # Internal nets named to match the .kicad_sch labels.
    voutp = Net('VOUTP'); voutn = Net('VOUTN')
    bypp  = Net('BYPP');  bypn  = Net('BYPN')
    adjp  = Net('ADJP');  adjn  = Net('ADJN')
    cbstp = Net('CBSTP'); cbstn = Net('CBSTN')
    cinvp = Net('CINVP'); cinvn = Net('CINVN')

    # Connect the LTC3265 by pin name (resolved via the OPA_PHONO symbol lib).
    u3['VIN']   += VIN
    u3['GND']   += GND
    u3['VOUTP'] += voutp
    u3['VOUTN'] += voutn
    u3['BYPP']  += bypp
    u3['BYPN']  += bypn
    u3['ADJP']  += adjp
    u3['ADJN']  += adjn
    u3['CBSTP'] += cbstp
    u3['CBSTN'] += cbstn
    u3['CINVP'] += cinvp
    u3['CINVN'] += cinvn

    # ---- VIN bypass (10u + 1u) ----
    decouple(VIN, GND, '10u', ref='C23', fp=FP_C0805)
    decouple(VIN, GND, '1u',  ref='C13', fp=FP_C0402)

    # ---- Flying caps ----
    # Boost flying cap between CBSTP <-> CBSTN.
    c16 = C('1u', ref='C16', fp=FP_C0402)
    c16[1] += cbstp; c16[2] += cbstn
    # Inverter flying cap between CINVP <-> CINVN.
    c14 = C('1u', ref='C14', fp=FP_C0402)
    c14[1] += cinvp; c14[2] += cinvn

    # ---- Raw boost / inverter outputs (pre-LDO) ----
    decouple(voutp, GND, '10u', ref='C26', fp=FP_C0805)
    decouple(voutn, GND, '10u', ref='C24', fp=FP_C0805)

    # ---- LDO bypass caps for low-noise reference ----
    decouple(bypp, GND, '1u', ref='C17', fp=FP_C0402)
    decouple(bypn, GND, '1u', ref='C18', fp=FP_C0402)

    # ---- LDO feedback dividers ----
    # +6V: VP -> R25(20.5k) -> ADJP -> R26(5.1k) -> GND
    r25 = R('20.5k', ref='R25')
    r26 = R('5.1k',  ref='R26')
    r25[1] += VP;   r25[2] += adjp
    r26[1] += adjp; r26[2] += GND

    # -6V: GND -> R27(5.1k) -> ADJN -> R28(20.5k) -> VN
    r27 = R('5.1k',  ref='R27')
    r28 = R('20.5k', ref='R28')
    r27[1] += GND;  r27[2] += adjn
    r28[1] += adjn; r28[2] += VN

    # ---- LDO output bulk + local decoupling ----
    decouple(VP, GND, '10u', ref='C27', fp=FP_C0805)
    decouple(VN, GND, '10u', ref='C28', fp=FP_C0805)
    decouple(VP, GND, '10u', ref='C15', fp=FP_C0805)
    decouple(VN, GND, '10u', ref='C25', fp=FP_C0805)
    # Per-IC decoupling living on the POWER sheet (close to U1/U2 in layout).
    decouple(VP, GND, '1u', ref='C19', fp=FP_C0402)
    decouple(VN, GND, '1u', ref='C20', fp=FP_C0402)
    decouple(VP, GND, '1u', ref='C21', fp=FP_C0402)
    decouple(VN, GND, '1u', ref='C22', fp=FP_C0402)


# ---------------------------------------------------------- RIAA channel

@subcircuit
def riaa_channel(name, sig_in, sig_out, VP, VN, GND,
                 stage1_inp, stage1_inn, stage1_out,
                 stage2_inp, stage2_inn, stage2_out,
                 servo_inp,  servo_inn,  servo_out,
                 refdes):
    """One channel: 2-stage gain with passive RIAA + DC servo.

    `stage1_*`, `stage2_*`, `servo_*` are the (+input, -input, output) pins
    of three op-amp gates allocated in the top level.
    `refdes` is a dict mapping schematic refdes -> the local component, so
    the LEFT and RIGHT instantiations get matching reference designators
    (R1 vs R13, R2 vs R14, ...).
    """
    rd = refdes

    # ---- Per-channel internal nets ----
    fb1     = Net(f'{name}_FB1')
    out1    = Net(f'{name}_OUT1')
    riaa    = Net(f'{name}_RIAA')
    riaa_rc = Net(f'{name}_RIAA_RC')
    fb2     = Net(f'{name}_FB2')
    out2    = Net(f'{name}_OUT2')
    trim    = Net(f'{name}_TRIM')
    fbtrim  = Net(f'{name}_FBTRIM')
    out_rc  = Net(f'{name}_OUT_RC')

    # ---- Cartridge load (47k || optional cap, both to GND) ----
    r_load = R('47k', ref=rd['R_LOAD'])             # R1  / R13
    c_load = C('NP', ref=rd['C_LOAD'], dnp=True)     # C1  / C7  (DNP)
    r_load[1] += sig_in; r_load[2] += GND
    c_load[1] += sig_in; c_load[2] += GND

    # ---- Stage 1: non-inverting amp, +30 dB ----
    # Gain = 1 + R_FB1 / R_GAIN1 = 1 + 16k / 499 ~= 33x  ~=  30.4 dB
    sig_in += stage1_inp                              # +IN <- cartridge
    fb1    += stage1_inn                              # -IN <- feedback node
    out1   += stage1_out                              # OUT
    r_fb1   = R('16k',  ref=rd['R_FB1'])              # R2  / R14
    r_gain1 = R('499R', ref=rd['R_GAIN1'])            # R3  / R15
    r_fb1[1]   += out1; r_fb1[2]   += fb1
    r_gain1[1] += fb1;  r_gain1[2] += GND

    # ---- Passive RIAA filter (between stages) ----
    #   OUT1 --[R_SER 16k]-- RIAA  -+-- C_HF 47n -- GND
    #                                |
    #                                +-- R_RIAA 2.32k -- RIAA_RC -+-- C_LF1 68n -- GND
    #                                                              +-- C_LF2 68n -- GND
    r_ser   = R('16k',  ref=rd['R_RIAA_SER'])         # R4  / R16
    r_riaa  = R('2.32k', ref=rd['R_RIAA'])            # R5  / R17
    c_hf    = C('47n',  ref=rd['C_HF'],  fp=FP_C1206) # C4  / C10
    c_lf1   = C('68n',  ref=rd['C_LF1'], fp=FP_C1210) # C2  / C8
    c_lf2   = C('68n',  ref=rd['C_LF2'], fp=FP_C1210) # C3  / C9
    r_ser[1]  += out1;    r_ser[2]  += riaa
    c_hf[1]   += riaa;    c_hf[2]   += GND
    r_riaa[1] += riaa;    r_riaa[2] += riaa_rc
    c_lf1[1]  += riaa_rc; c_lf1[2]  += GND
    c_lf2[1]  += riaa_rc; c_lf2[2]  += GND

    # ---- Stage 2: non-inverting amp on OPA1612, +30 dB ----
    riaa += stage2_inp                                # +IN <- RIAA filter out
    fb2  += stage2_inn                                # -IN <- feedback node
    out2 += stage2_out                                # OUT
    r_fb2   = R('16k',  ref=rd['R_FB2'])              # R7  / R19
    r_gain2 = R('499R', ref=rd['R_GAIN2'])            # R6  / R8
    r_fb2[1]   += out2; r_fb2[2]   += fb2
    r_gain2[1] += fb2;  r_gain2[2] += GND

    # ---- DC servo (OPA1644 integrator) ----
    # Integrates OUT2 vs. GND and trims back into the stage 2 feedback path.
    # Topology (best inference; verify against rendered schematic):
    #   OUT2 --[R9 47k]-- TRIM --[stage2 -IN summing]
    #   TRIM --[R10 47k]-- (servo +IN summing reference / GND ref)
    #   servo -IN <- FBTRIM, feedback through R11 47k and integrator C5 1u
    trim   += servo_inp                               # servo +IN
    fbtrim += servo_inn                               # servo -IN
    out_rc += servo_out                               # servo OUT
    r_servo_in   = R('47k', ref=rd['R_SRVO_IN'])      # R9  / R21
    r_servo_ref  = R('47k', ref=rd['R_SRVO_REF'])     # R10 / R22
    r_servo_fb   = R('47k', ref=rd['R_SRVO_FB'])      # R11 / R23
    c_servo_int  = C('1u',  ref=rd['C_SRVO'])         # C5  / C11
    r_servo_in[1]  += out2;   r_servo_in[2]  += trim
    r_servo_ref[1] += trim;   r_servo_ref[2] += GND
    r_servo_fb[1]  += fbtrim; r_servo_fb[2]  += out_rc
    c_servo_int[1] += fbtrim; c_servo_int[2] += out_rc

    # ---- Output series resistor ----
    r_out = R('499R', ref=rd['R_OUT'])                # R12 / R24
    r_out[1] += out2; r_out[2] += sig_out


# -------------------------------------------------------------- TOP LEVEL

# --- Top-level nets ---
GND  = Net('GND'); GND.drive = 1
VBUS = Net('VBUS')                 # +5V from USB-C
VP   = Net('+6V')                  # positive rail
VN   = Net('-6V')                  # negative rail
IN_L  = Net('IN_L');  IN_R  = Net('IN_R')
OUT_L = Net('OUT_L'); OUT_R = Net('OUT_R')
CC1  = Net('CC1');  CC2  = Net('CC2')

# --- USB-C receptacle (J3) ---
j3 = Part('OPA_PHONO', 'UJC-HP-3-SMT-TR', ref='J3',
          footprint='OPA_PHONO:CUI_UJC-HP-3-SMT-TR')
j3['VBUS'] += VBUS
j3['GND']  += GND
j3['CC1']  += CC1
j3['CC2']  += CC2
# All four shield tabs to GND.  The lib has SHIELD as a multi-pin name; loop
# over any pin whose name starts with 'SHIELD'.
for p in j3.pins:
    if p.name and p.name.startswith('SHIELD'):
        p += GND

# CC1/CC2 5.1k pulldowns (configures port as USB-C UFP / sink).
r29 = R('5.1k', ref='R29');  r29[1] += CC1; r29[2] += GND
r30 = R('5.1k', ref='R30');  r30[1] += CC2; r30[2] += GND

# --- RCA jacks (Switchcraft PJRAS2X1S01X dual mono) ---
# T1 = top tip, T2 = bottom tip, S1/S2 = shells (ground).
j2 = Part('OPA_PHONO', 'PJRAS2X1S01X', ref='J2',
          footprint='OPA_PHONO:PJRAS2X1S01X')          # input
j2['T1'] += IN_L; j2['T2'] += IN_R
j2['S1'] += GND;  j2['S2'] += GND

j1 = Part('OPA_PHONO', 'PJRAS2X1S01X', ref='J1',
          footprint='OPA_PHONO:PJRAS2X1S01X')          # output
j1['T1'] += OUT_L; j1['T2'] += OUT_R
j1['S1'] += GND;   j1['S2'] += GND

# Mechanical (Hammond enclosure) - non-electrical, listed here for BOM parity.
n1 = Part('Mechanical', 'Housing', ref='N1', footprint='')

# --- U1 OPA1644 (quad) and U2 OPA1612 (dual) live at top level so the same
# physical chip is shared between the two channel subcircuits ---
u1 = Part('OPA_PHONO', 'OPA1644AxD', ref='U1', footprint=FP_SOIC14)
u2 = Part('Amplifier_Operational', 'OPA1612AxD', ref='U2', footprint=FP_SOIC8)

# Power pin connections (OPA1644: V+ pin 11, V- pin 4 ; OPA1612: V+ pin 8, V- pin 4).
u1[11] += VP; u1[4] += VN
u2[8]  += VP; u2[4] += VN

# Op-amp local decoupling (the per-IC 1u/10u live on POWER sheet via power()).

# --- Power subcircuit ---
power(VBUS, VP, VN, GND)

# --- Channel instantiations ---
#
# OPA1644 pinout (per TI):
#   gate A: OUT 1, -IN 2, +IN 3
#   gate B: OUT 7, -IN 6, +IN 5
#   gate C: OUT 8, -IN 9, +IN 10
#   gate D: OUT 14, -IN 13, +IN 12
#
# OPA1612 pinout:
#   gate A: OUT 1, -IN 2, +IN 3
#   gate B: OUT 7, -IN 6, +IN 5
#
# LEFT  channel: U1 gate A (stage 1) + U1 gate B (servo) + U2 gate A (stage 2)
# RIGHT channel: U1 gate C (stage 1) + U1 gate D (servo) + U2 gate B (stage 2)

LEFT_REFDES = {
    'R_LOAD':       'R1',
    'C_LOAD':       'C1',
    'R_FB1':        'R2',
    'R_GAIN1':      'R3',
    'R_RIAA_SER':   'R4',
    'R_RIAA':       'R5',
    'C_HF':         'C4',
    'C_LF1':        'C2',
    'C_LF2':        'C3',
    'R_FB2':        'R7',
    'R_GAIN2':      'R8',
    'R_SRVO_IN':    'R9',
    'R_SRVO_REF':   'R10',
    'R_SRVO_FB':    'R11',
    'C_SRVO':       'C5',
    'R_OUT':        'R12',
}

RIGHT_REFDES = {
    'R_LOAD':       'R13',
    'C_LOAD':       'C7',
    'R_FB1':        'R14',
    'R_GAIN1':      'R15',
    'R_RIAA_SER':   'R16',
    'R_RIAA':       'R17',
    'C_HF':         'C10',
    'C_LF1':        'C8',
    'C_LF2':        'C9',
    'R_FB2':        'R19',
    'R_GAIN2':      'R6',
    'R_SRVO_IN':    'R21',
    'R_SRVO_REF':   'R22',
    'R_SRVO_FB':    'R23',
    'C_SRVO':       'C11',
    'R_OUT':        'R24',
}

riaa_channel(
    'L', IN_L, OUT_L, VP, VN, GND,
    stage1_inp=u1[3],  stage1_inn=u1[2],  stage1_out=u1[1],     # OPA1644 gate A
    stage2_inp=u2[3],  stage2_inn=u2[2],  stage2_out=u2[1],     # OPA1612 gate A
    servo_inp =u1[5],  servo_inn =u1[6],  servo_out =u1[7],     # OPA1644 gate B
    refdes=LEFT_REFDES,
)
riaa_channel(
    'R', IN_R, OUT_R, VP, VN, GND,
    stage1_inp=u1[10], stage1_inn=u1[9],  stage1_out=u1[8],     # OPA1644 gate C
    stage2_inp=u2[5],  stage2_inn=u2[6],  stage2_out=u2[7],     # OPA1612 gate B
    servo_inp =u1[12], servo_inn =u1[13], servo_out =u1[14],    # OPA1644 gate D
    refdes=RIGHT_REFDES,
)


if __name__ == '__main__':
    ERC()
    generate_netlist(file_='opa_phono.net')
