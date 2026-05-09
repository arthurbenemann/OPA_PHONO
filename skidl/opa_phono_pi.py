"""
OPA_PHONO + Raspberry Pi HAT (ADC) — SKiDL design.

Combines the existing OPA1612/OPA1644 RIAA phono preamp with a PCM1863
stereo ADC (HiFiBerry-style) on a Raspberry Pi 40-pin GPIO header.

Power flow:
    Pi 5V (header pin 2/4) -> LTC3265 charge pump -> +-6V analog rails
    Pi 3.3V (header pin 1)  -> ADC DVDD, EEPROM VCC

Audio flow:
    RCA L/R -> RIAA preamp -> AC-coupling -> PCM1863 single-ended inputs
    PCM1863 I2S out -> Pi I2S (BCK/LRCK/DIN)
    PCM1863 control via I2C0 on BCM2/BCM3
    HAT ID EEPROM (24C32) on ID_SD/ID_SC

Run:
    python opa_phono_pi.py            # generates opa_phono_pi.net
    python opa_phono_pi.py --erc      # run ERC only
"""

from skidl import (
    Part, Net, Bus, generate_netlist, ERC, TEMPLATE, NC, POWER, subcircuit,
)


# -----------------------------------------------------------------------------
# Part templates
# -----------------------------------------------------------------------------
R = Part("Device", "R_US", dest=TEMPLATE, footprint="Resistor_SMD:R_0402_1005Metric")
C = Part("Device", "C", dest=TEMPLATE, footprint="Capacitor_SMD:C_0402_1005Metric")
C0805 = Part("Device", "C", dest=TEMPLATE, footprint="Capacitor_SMD:C_0805_2012Metric")
C1206 = Part("Device", "C", dest=TEMPLATE, footprint="Capacitor_SMD:C_1206_3216Metric")
C1210 = Part("Device", "C", dest=TEMPLATE, footprint="Capacitor_SMD:C_1210_3225Metric")


# -----------------------------------------------------------------------------
# RIAA preamp — one channel
#
# Stage 1 (OPA1644, 1/4): non-inverting flat gain ~30x
#     Rin (47k input load)  || Cin (NP, optional cartridge cap)
#     gain = 1 + Rf/Rg with Rf=16k, Rg=499R+(small)  -> high gain
#
# Stage 2 (OPA1644, 1/4): RIAA filter — passive RC between stages
#     R(2.32k) + C(68n) + C(47n) network
#
# Stage 3 (OPA1612, 1/2): output buffer with 47k pull, 499R series, 1u AC-couple
#
# Values lifted from PCB/RIAA_PHONO.kicad_sch and PCB/OPA_PHONO.bom.csv.
# -----------------------------------------------------------------------------
@subcircuit
def riaa_channel(audio_in, audio_out, vplus, vminus, gnd, opa_quad_a, opa_quad_b, opa_dual):
    """
    One channel of the RIAA preamp.

    audio_in   : single-ended input from RCA jack
    audio_out  : line-level output to ADC anti-alias filter
    opa_quad_a : one section of the OPA1644 (first gain stage)
    opa_quad_b : one section of the OPA1644 (RIAA stage)
    opa_dual   : one section of the OPA1612 (output buffer)
    """
    # Stage 1: flat gain
    r_in = R(value="47k", ref="R_IN")           # input load
    c_in = C(value="NP", ref="C_IN")            # placeholder for cartridge cap
    rf1  = R(value="16k", ref="R_F1")
    rg1  = R(value="499R", ref="R_G1")
    rg1b = R(value="16k", ref="R_G1B")          # series to virtual ground

    audio_in & r_in & gnd
    audio_in & c_in & gnd
    audio_in += opa_quad_a["+"]
    n_fb1 = Net()                               # inverting node of stage 1
    n_fb1 += opa_quad_a["-"]
    rg1["~"][1] += n_fb1
    rg1["~"][2] += gnd                          # gain-set leg to ground
    rg1b["~"][1] += n_fb1
    rg1b["~"][2] += gnd                         # parallel leg
    rf1["~"][1] += n_fb1
    rf1["~"][2] += opa_quad_a["~"]              # output node

    n_s1_out = opa_quad_a["~"]

    # Inter-stage RIAA passive network: 2.32k series, 68n shunt, 47n shunt
    r_riaa = R(value="2.32k", ref="R_RIAA")
    c_riaa1 = C1210(value="68n", ref="C_R1")
    c_riaa2 = C1206(value="47n", ref="C_R2")

    n_riaa_mid = Net()
    r_riaa["~"][1] += n_s1_out
    r_riaa["~"][2] += n_riaa_mid
    c_riaa1["~"][1] += n_riaa_mid
    c_riaa1["~"][2] += gnd
    c_riaa2["~"][1] += n_riaa_mid
    c_riaa2["~"][2] += gnd

    # Stage 2: RIAA-shaped gain
    rf2 = R(value="16k", ref="R_F2")
    rg2 = R(value="499R", ref="R_G2")
    rg2b = R(value="16k", ref="R_G2B")
    c_riaa3 = C1210(value="68n", ref="C_R3")    # feedback shunt cap

    opa_quad_b["+"] += n_riaa_mid
    n_fb2 = Net()
    n_fb2 += opa_quad_b["-"]
    rg2["~"][1] += n_fb2
    rg2["~"][2] += gnd
    rg2b["~"][1] += n_fb2
    rg2b["~"][2] += gnd
    rf2["~"][1] += n_fb2
    rf2["~"][2] += opa_quad_b["~"]
    c_riaa3["~"][1] += n_fb2
    c_riaa3["~"][2] += opa_quad_b["~"]

    # Stage 3: output buffer (OPA1612)
    r_pull = R(value="47k", ref="R_PULL")
    r_ser  = R(value="499R", ref="R_SER")
    c_ac   = C(value="1u", ref="C_AC")
    r_term = R(value="47k", ref="R_TERM")

    opa_dual["+"] += opa_quad_b["~"]
    opa_dual["-"] += opa_dual["~"]              # unity buffer
    r_pull["~"][1] += opa_quad_b["~"]
    r_pull["~"][2] += gnd

    n_buf = opa_dual["~"]
    r_ser["~"][1] += n_buf
    r_ser["~"][2] += audio_out
    c_ac["~"][1] += audio_out                   # series AC-couple to ADC side
    # NB: in original board AC-couple is via C5/C6 1u with no series cap;
    # we keep the existing topology and only add the ADC anti-alias filter
    # later. Tie second leg of C_AC to audio_out for placeholder; real
    # AC-couple sits in adc_input_filter() below.
    c_ac["~"][2] += audio_out
    r_term["~"][1] += audio_out
    r_term["~"][2] += gnd

    # Op-amp supply pins (handled by caller already; we just decoup here).
    cd_p = C(value="1u", ref="C_DPP")
    cd_n = C(value="1u", ref="C_DPN")
    cd_p["~"][1] += vplus
    cd_p["~"][2] += gnd
    cd_n["~"][1] += vminus
    cd_n["~"][2] += gnd


# -----------------------------------------------------------------------------
# LTC3265 +-6V charge pump, fed from Pi 5V rail
#
# Component values from PCB/POWER.kicad_sch:
#     C_INVP / C_INVN : 1u flying caps
#     C_BSTP / C_BSTN : 1u boost caps
#     C_OUT pos/neg   : 10u
#     ADJ divider     : 20.5k / 5.1k -> ~+-6V
# -----------------------------------------------------------------------------
@subcircuit
def ltc3265_psu(vin_5v, vplus_6v, vminus_6v, gnd):
    """+-6V charge pump from Pi 5V."""
    u3 = Part(
        "Regulator_SwitchedCapacitor", "LTC3265",
        value="LTC3265",
        footprint="Package_DFN_QFN:DFN-18-1EP_3x5mm_P0.5mm_EP1.66x4.4mm",
    )
    # NB: pin names follow LTC3265 datasheet. Adjust if local KiCad symbol
    # uses different labels.
    u3["VIN"] += vin_5v
    u3["GND"] += gnd
    u3["EP"]  += gnd                     # exposed pad

    # Input bulk
    c_in = C0805(value="10u", ref="C_VIN")
    c_in["~"][1] += vin_5v
    c_in["~"][2] += gnd

    # Flying caps for inverting pump
    c_invp = C(value="1u", ref="C_INVP")
    c_invn = C(value="1u", ref="C_INVN")
    c_invp["~"][1] += u3["CINVP"]; c_invp["~"][2] += u3["CINVN"]
    # second flying cap on the boost side
    c_bst = C(value="1u", ref="C_BST")
    c_bst["~"][1] += u3["CBSTP"]; c_bst["~"][2] += u3["CBSTN"]

    # Bypass caps (BYPP/BYPN)
    c_byp_p = C(value="1u", ref="C_BYPP")
    c_byp_n = C(value="1u", ref="C_BYPN")
    c_byp_p["~"][1] += u3["BYPP"]; c_byp_p["~"][2] += gnd
    c_byp_n["~"][1] += u3["BYPN"]; c_byp_n["~"][2] += gnd

    # +6V output: ADJP divider 20.5k / 5.1k
    r_top_p = R(value="20.5k", ref="R_ADJP_TOP")
    r_bot_p = R(value="5.1k",  ref="R_ADJP_BOT")
    r_top_p["~"][1] += u3["VOUTP"]
    r_top_p["~"][2] += u3["ADJP"]
    r_bot_p["~"][1] += u3["ADJP"]
    r_bot_p["~"][2] += gnd
    c_out_p1 = C0805(value="10u", ref="C_OUTP1")
    c_out_p2 = C0805(value="10u", ref="C_OUTP2")
    c_out_p1["~"][1] += u3["VOUTP"]; c_out_p1["~"][2] += gnd
    c_out_p2["~"][1] += u3["VOUTP"]; c_out_p2["~"][2] += gnd
    u3["VOUTP"] += vplus_6v

    # -6V output: ADJN divider 20.5k / 5.1k
    r_top_n = R(value="20.5k", ref="R_ADJN_TOP")
    r_bot_n = R(value="5.1k",  ref="R_ADJN_BOT")
    r_top_n["~"][1] += u3["VOUTN"]
    r_top_n["~"][2] += u3["ADJN"]
    r_bot_n["~"][1] += u3["ADJN"]
    r_bot_n["~"][2] += gnd
    c_out_n1 = C0805(value="10u", ref="C_OUTN1")
    c_out_n2 = C0805(value="10u", ref="C_OUTN2")
    c_out_n1["~"][1] += u3["VOUTN"]; c_out_n1["~"][2] += gnd
    c_out_n2["~"][1] += u3["VOUTN"]; c_out_n2["~"][2] += gnd
    u3["VOUTN"] += vminus_6v


# -----------------------------------------------------------------------------
# PCM1863 stereo ADC + anti-alias filter
#
# Single-ended input mode (VINL1 / VINR1 used; VINLx-/VINRx- via REFGND).
# Master mode: PCM1863 generates BCK/LRCK from internal PLL; Pi receives
# audio as I2S slave on BCM18/BCM19/BCM20.
# Hardware control mode is not used here; I2C address selected by ADR pin
# tied via 47k -> address 0x4A (per HiFiBerry-style boards).
# -----------------------------------------------------------------------------
@subcircuit
def adc_input_filter(line_in, adc_pin_pos, adc_pin_neg, gnd):
    """Single-ended AA filter into a PCM1863 differential input."""
    r_ser = R(value="3.3k", ref="R_AAS")
    c_ac  = C0805(value="2.2u", ref="C_AAC")        # AC couple
    r_bias = R(value="22k", ref="R_BIAS")           # bias to half-VREF (via REFGND through next stage)
    c_aa   = C(value="470p", ref="C_AA")            # anti-alias to GND

    # Series AC-couple
    c_ac["~"][1] += line_in
    n_after_c = Net()
    c_ac["~"][2] += n_after_c
    r_ser["~"][1] += n_after_c
    r_ser["~"][2] += adc_pin_pos
    c_aa["~"][1] += adc_pin_pos
    c_aa["~"][2] += gnd

    # Bias: keep N input at REFGND through 22k (datasheet recommended)
    r_bias["~"][1] += adc_pin_neg
    r_bias["~"][2] += gnd


@subcircuit
def pcm1863(line_l, line_r,
            avdd_3v3, dvdd_3v3, gnd,
            i2s_bck, i2s_lrck, i2s_dout,
            i2c_sda, i2c_scl):
    u_adc = Part(
        "Analog_ADC", "PCM1863",
        value="PCM1863",
        footprint="Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm",
    )

    # Power
    u_adc["AVDD"] += avdd_3v3
    u_adc["DVDD"] += dvdd_3v3
    u_adc["LDO_OUT"] += NC                           # internal LDO; external cap below
    u_adc["AGND"] += gnd
    u_adc["DGND"] += gnd

    # Decoupling
    for ref in ("C_AVDD", "C_DVDD"):
        c = C(value="1u", ref=ref)
        c["~"][1] += avdd_3v3 if ref == "C_AVDD" else dvdd_3v3
        c["~"][2] += gnd
    c_ldo = C(value="1u", ref="C_LDO")
    c_ldo["~"][1] += u_adc["LDO_OUT"]
    c_ldo["~"][2] += gnd
    c_vref = C0805(value="10u", ref="C_VREF")
    c_vref["~"][1] += u_adc["VREF"]
    c_vref["~"][2] += gnd

    # Audio inputs: drive VINL1+/VINR1+ single-ended; VINL1-/VINR1- biased.
    adc_input_filter(line_l, u_adc["VINL1+"], u_adc["VINL1-"], gnd)
    adc_input_filter(line_r, u_adc["VINR1+"], u_adc["VINR1-"], gnd)

    # Ground unused secondary inputs
    for pin in ("VINL2+", "VINL2-", "VINR2+", "VINR2-"):
        u_adc[pin] += NC

    # I2S to Pi (PCM1863 master, Pi slave on its I2S peripheral)
    u_adc["BCK"]  += i2s_bck
    u_adc["LRCK"] += i2s_lrck
    u_adc["DOUT"] += i2s_dout

    # I2C control
    u_adc["SCL"] += i2c_scl
    u_adc["SDA"] += i2c_sda

    # I2C address select: ADR1=GND, ADR2=GND -> 0x4A
    u_adc["ADR1"] += gnd
    u_adc["ADR2"] += gnd

    # Pull-ups for I2C live on the EEPROM block (shared bus segment is
    # on the Pi side). Add local pull-ups in case ID bus is separate:
    r_sda = R(value="4.7k", ref="R_SDA")
    r_scl = R(value="4.7k", ref="R_SCL")
    r_sda["~"][1] += i2c_sda; r_sda["~"][2] += dvdd_3v3
    r_scl["~"][1] += i2c_scl; r_scl["~"][2] += dvdd_3v3


# -----------------------------------------------------------------------------
# 24C32 HAT ID EEPROM on ID_SD / ID_SC (BCM 0/1, header 27/28).
# Per Pi HAT spec: device address 0x50, 32 kbit, 3.3V.
# -----------------------------------------------------------------------------
@subcircuit
def hat_eeprom(id_sd, id_sc, vcc_3v3, gnd):
    u_ee = Part(
        "Memory_EEPROM", "24LC32",
        value="24C32",
        footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    )
    u_ee["VCC"] += vcc_3v3
    u_ee["VSS"] += gnd
    u_ee["A0"]  += gnd
    u_ee["A1"]  += gnd
    u_ee["A2"]  += gnd
    u_ee["WP"]  += gnd                                # WP=GND lets the Pi bootloader
                                                      # write the HAT image once,
                                                      # tie to VCC after programming
    u_ee["SDA"] += id_sd
    u_ee["SCL"] += id_sc

    # Bypass + ID bus pull-ups (HAT spec requires 3.9k pull-ups on ID bus).
    c_bp = C(value="100n", ref="C_EEP")
    c_bp["~"][1] += vcc_3v3; c_bp["~"][2] += gnd

    r_sd = R(value="3.9k", ref="R_IDSD")
    r_sc = R(value="3.9k", ref="R_IDSC")
    r_sd["~"][1] += id_sd; r_sd["~"][2] += vcc_3v3
    r_sc["~"][1] += id_sc; r_sc["~"][2] += vcc_3v3


# -----------------------------------------------------------------------------
# Top-level
# -----------------------------------------------------------------------------
def build():
    # Power nets
    pi_5v   = Net("PI_5V")
    pi_3v3  = Net("PI_3V3")
    vplus   = Net("+6V")
    vminus  = Net("-6V")
    gnd     = Net("GND")
    pi_5v.drive  = POWER
    pi_3v3.drive = POWER
    vplus.drive  = POWER
    vminus.drive = POWER
    gnd.drive    = POWER

    # Audio nets
    in_l  = Net("IN_L")
    in_r  = Net("IN_R")
    out_l = Net("OUT_L")
    out_r = Net("OUT_R")

    # I2S / I2C nets
    i2s_bck   = Net("I2S_BCK")
    i2s_lrck  = Net("I2S_LRCK")
    i2s_dout  = Net("I2S_DOUT")        # ADC -> Pi
    i2c_sda   = Net("I2C_SDA")
    i2c_scl   = Net("I2C_SCL")
    id_sd     = Net("ID_SD")
    id_sc     = Net("ID_SC")

    # ---- Op-amps (shared between channels) ----
    u1_quad = Part(
        "Amplifier_Operational", "OPA1644",
        value="OPA1644AID",
        footprint="Package_SO:SOIC-14_3.9x8.7mm_P1.27mm",
    )
    u2_dual = Part(
        "Amplifier_Operational", "OPA1612",
        value="OPA1612AID",
        footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    )

    # Tie op-amp supply pins. Pin names per KiCad symbols ("V+", "V-").
    u1_quad["V+"] += vplus
    u1_quad["V-"] += vminus
    u2_dual["V+"] += vplus
    u2_dual["V-"] += vminus

    # OPA1644 has 4 sections (units 1..4); OPA1612 has 2 sections (1..2).
    # Use unit() accessor in SKiDL: .unit['unit_name'] or numeric.
    riaa_channel(in_l, out_l, vplus, vminus, gnd,
                 u1_quad.unit[1], u1_quad.unit[2], u2_dual.unit[1])
    riaa_channel(in_r, out_r, vplus, vminus, gnd,
                 u1_quad.unit[3], u1_quad.unit[4], u2_dual.unit[2])

    # ---- Power supply ----
    ltc3265_psu(pi_5v, vplus, vminus, gnd)

    # ---- ADC ----
    pcm1863(out_l, out_r,
            avdd_3v3=pi_3v3, dvdd_3v3=pi_3v3, gnd=gnd,
            i2s_bck=i2s_bck, i2s_lrck=i2s_lrck, i2s_dout=i2s_dout,
            i2c_sda=i2c_sda, i2c_scl=i2c_scl)

    # ---- HAT EEPROM ----
    hat_eeprom(id_sd, id_sc, pi_3v3, gnd)

    # ---- RCA jacks (preamp inputs) ----
    rca_l = Part(
        "OPA_PHONO", "PJRAS2X1S01X", value="RCA_L",
        footprint="OPA_PHONO:PJRAS2X1S01X",
    )
    rca_r = Part(
        "OPA_PHONO", "PJRAS2X1S01X", value="RCA_R",
        footprint="OPA_PHONO:PJRAS2X1S01X",
    )
    rca_l[1] += in_l;  rca_l[2] += gnd
    rca_r[1] += in_r;  rca_r[2] += gnd

    # ---- Raspberry Pi 40-pin GPIO header ----
    # Pin map (Pi B+ / 2 / 3 / 4 / 5):
    #     1  3V3        2  5V
    #     3  BCM2 SDA   4  5V
    #     5  BCM3 SCL   6  GND
    #     7  BCM4       8  BCM14
    #     9  GND       10  BCM15
    #    11  BCM17     12  BCM18  <- I2S BCK
    #    13  BCM27     14  GND
    #    15  BCM22     16  BCM23
    #    17  3V3       18  BCM24
    #    19  BCM10     20  GND
    #    21  BCM9      22  BCM25
    #    23  BCM11     24  BCM8
    #    25  GND       26  BCM7
    #    27  ID_SD     28  ID_SC
    #    29  BCM5      30  GND
    #    31  BCM6      32  BCM12
    #    33  BCM13     34  GND
    #    35  BCM19 LRCK 36 BCM16
    #    37  BCM26     38  BCM20  <- I2S DIN
    #    39  GND       40  BCM21
    j_pi = Part(
        "Connector_Generic", "Conn_02x20_Odd_Even",
        value="RPi_HEADER",
        footprint="Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical",
    )

    # Power
    j_pi[1]  += pi_3v3
    j_pi[17] += pi_3v3
    j_pi[2]  += pi_5v
    j_pi[4]  += pi_5v
    for gnd_pin in (6, 9, 14, 20, 25, 30, 34, 39):
        j_pi[gnd_pin] += gnd

    # I2C control bus
    j_pi[3] += i2c_sda    # BCM2
    j_pi[5] += i2c_scl    # BCM3

    # I2S
    j_pi[12] += i2s_bck   # BCM18
    j_pi[35] += i2s_lrck  # BCM19
    j_pi[38] += i2s_dout  # BCM20

    # HAT ID
    j_pi[27] += id_sd
    j_pi[28] += id_sc

    # All other GPIO pins left unconnected (NC) so ERC stays clean.
    for n in (7, 8, 10, 11, 13, 15, 16, 18, 19, 21, 22, 23, 24, 26,
              29, 31, 32, 33, 36, 37, 40):
        j_pi[n] += NC


if __name__ == "__main__":
    import sys
    build()
    if "--erc" in sys.argv:
        ERC()
    else:
        ERC()
        generate_netlist(file_="opa_phono_pi.net")
