"""
Generate a CSV BOM from the SKiDL design.

Builds the circuit, then walks every Part instance in the default circuit
and groups by (Manufacturer, MPN, Value, Footprint). Emits one row per
group with the comma-joined designator list and total quantity.

Run:
    python bom.py                  # writes opa_phono_pi.bom.csv
    python bom.py path/to/out.csv  # custom output path
"""

import csv
import re
import sys
from collections import defaultdict

import builtins

import opa_phono_pi  # builds the circuit on import-time call below

# Hide ERC noise from this run; opa_phono_pi.build() does the real work.
opa_phono_pi.build()

OUTPUT = sys.argv[1] if len(sys.argv) > 1 else "opa_phono_pi.bom.csv"


def ref_sort_key(ref):
    """Sort designators naturally: R1, R2, ..., R10 (not R1, R10, R2)."""
    m = re.match(r"([A-Za-z#]+)(\d+)", ref)
    if not m:
        return (ref, 0)
    return (m.group(1), int(m.group(2)))


def field(part, name, default=""):
    return part.fields.get(name, default) if hasattr(part, "fields") else default


groups = defaultdict(list)
for p in builtins.default_circuit.parts:
    key = (
        field(p, "Manufacturer"),
        field(p, "MPN"),
        getattr(p, "value", "") or "",
        getattr(p, "footprint", "") or "",
    )
    groups[key].append(p.ref)


with open(OUTPUT, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Designator", "Qty", "Value", "Manufacturer", "MPN", "Footprint"])
    rows = []
    for (mfr, mpn, value, fp), refs in groups.items():
        refs_sorted = sorted(refs, key=ref_sort_key)
        rows.append([
            ", ".join(refs_sorted),
            len(refs),
            value,
            mfr,
            mpn,
            fp,
        ])
    # Sort: ICs and connectors first (U/J), then passives by value
    rows.sort(key=lambda r: (
        0 if r[0].startswith(("U", "J")) else 1,
        r[4] or "ZZZ",   # group rows with no MPN at the bottom of each section
        r[2],
    ))
    w.writerows(rows)

print(f"Wrote {OUTPUT} ({sum(int(r[1]) for r in rows)} parts in {len(rows)} lines).")
