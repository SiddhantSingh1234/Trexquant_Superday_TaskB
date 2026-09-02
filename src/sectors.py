"""Phase 3 helper — sector classification.

78%+ automated: join our universe on ISIN against NSE's current
`ind_niftytotalmarket_list.csv` (752 names, carries both Industry and ISIN Code).
The names that file cannot contain — delisted / renamed companies — are
hand-classified below into NSE's **22 official industry names, used verbatim**.

⚠️ Disclosure (also in the P3 report): this classification is **current, not
point-in-time**. A company reclassified since 2015 carries today's label
throughout its history. Acceptable because `sector` drives only *optional*
sector-neutralization and red-team test 7 — never a scored feature on its own.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import REPO_ROOT

# The NSE current total-market list, downloaded once and cached (build-time
# network, exactly like P2's raw files). P3 runtime reads only this cache.
SECTOR_CSV: Path = REPO_ROOT / "data" / "raw" / "nse_meta" / "ind_niftytotalmarket_list.csv"

# NSE's 22 official industry names — the ONLY permitted values. Verbatim from
# PRE_BUILD_TASKS.md T2 / IMPLEMENTATION_PLAN.md P3.
NSE_INDUSTRIES: frozenset[str] = frozenset({
    "Automobile and Auto Components", "Capital Goods", "Chemicals",
    "Construction", "Construction Materials", "Consumer Durables",
    "Consumer Services", "Diversified", "Fast Moving Consumer Goods",
    "Financial Services", "Forest Materials", "Healthcare",
    "Information Technology", "Media Entertainment & Publication",
    "Metals & Mining", "Oil Gas & Consumable Fuels", "Power", "Realty",
    "Services", "Telecommunication", "Textiles", "Utilities",
})

# Fallback label for anything still unresolved (only expected on the synthetic
# fixture, where symbols are SYM000… and no NSE file matches).
UNKNOWN_SECTOR = "Diversified"

# --------------------------------------------------------------------------- #
# Hand classification — the ~delisted/renamed names NSE's current list omits.   #
# Each entry verified against the company's actual line of business. Judgement  #
# calls (holding companies, multi-segment firms) are listed in the P3 report.   #
# --------------------------------------------------------------------------- #
HAND_SECTOR: dict[str, str] = {
    # --- Financial Services (banks / NBFCs / broking / insurance) ---
    "ALBK": "Financial Services", "ANDHRABANK": "Financial Services",
    "ORIENTBANK": "Financial Services", "SYNDIBANK": "Financial Services",
    "INGVYSYABK": "Financial Services", "DHFL": "Financial Services",
    "GRUH": "Financial Services", "HDFC": "Financial Services",
    "REPCOHOME": "Financial Services", "CAPF": "Financial Services",
    "SRTRANSFIN": "Financial Services", "SREINFRA": "Financial Services",
    "RELCAPITAL": "Financial Services", "IDFC": "Financial Services",
    "BHARATFIN": "Financial Services", "SKSMICRO": "Financial Services",
    "EQUITAS": "Financial Services", "UJJIVAN": "Financial Services",
    "CARERATING": "Financial Services", "ANGELBRKG": "Financial Services",
    "ISEC": "Financial Services", "IBVENTURES": "Financial Services",
    "DHANI": "Financial Services", "PEL": "Financial Services",
    "PFS": "Financial Services",
    # --- Healthcare (pharma / diagnostics / CRO) ---
    "RANBAXY": "Healthcare", "SANOFI": "Healthcare", "ASTRAZEN": "Healthcare",
    "SHASUNPHAR": "Healthcare", "DISHMAN": "Healthcare", "SUVEN": "Healthcare",
    "JBCHEPHARM": "Healthcare", "BLISSGVS": "Healthcare",
    "MOREPENLAB": "Healthcare", "IOLCP": "Healthcare", "VIMTALABS": "Healthcare",
    # --- Information Technology ---
    "MINDTREE": "Information Technology", "HEXAWARE": "Information Technology",
    "NIITTECH": "Information Technology", "POLARIS": "Information Technology",
    "GEOMETRIC": "Information Technology", "MAJESCO": "Information Technology",
    "ROLTA": "Information Technology", "SUBEX": "Information Technology",
    "TAKE": "Information Technology", "RSSOFTWARE": "Information Technology",
    "8KMILES": "Information Technology", "HCL-INSYS": "Information Technology",
    # --- Oil Gas & Consumable Fuels ---
    "CAIRN": "Oil Gas & Consumable Fuels", "ESSAROIL": "Oil Gas & Consumable Fuels",
    "ABAN": "Oil Gas & Consumable Fuels", "GSPL": "Oil Gas & Consumable Fuels",
    "GUJGASLTD": "Oil Gas & Consumable Fuels", "GUJRATGAS": "Oil Gas & Consumable Fuels",
    "TIDEWATER": "Oil Gas & Consumable Fuels",
    # --- Automobile and Auto Components ---
    "AMTEKAUTO": "Automobile and Auto Components",
    "AMTEKINDIA": "Automobile and Auto Components",
    "ATULAUTO": "Automobile and Auto Components",
    "PRICOL": "Automobile and Auto Components",
    # --- Metals & Mining ---
    "PRAKASH": "Metals & Mining", "ARCOTECH": "Metals & Mining",
    "TATAMETALI": "Metals & Mining", "TATASPONGE": "Metals & Mining",
    "TATASTLBSL": "Metals & Mining", "TINPLATE": "Metals & Mining",
    # --- Chemicals ---
    "BEPL": "Chemicals", "BODALCHEM": "Chemicals", "KIRIINDUS": "Chemicals",
    "MEGH": "Chemicals", "NOCIL": "Chemicals", "PHILIPCARB": "Chemicals",
    "TIRUMALCHM": "Chemicals", "GUJALKALI": "Chemicals", "FINEORG": "Chemicals",
    "IPL": "Chemicals", "MONSANTO": "Chemicals", "GOACARBON": "Chemicals",
    "JINDALPOLY": "Chemicals", "POLYPLEX": "Chemicals", "IOLCP_DUP": "Chemicals",
    "DWARKESH": "Fast Moving Consumer Goods",
    # --- Textiles ---
    "BOMDYEING": "Textiles", "RAYMOND": "Textiles", "HIMATSEIDE": "Textiles",
    "JBFIND": "Textiles", "SINTEX": "Textiles", "MIRZAINT": "Consumer Durables",
    # --- Media Entertainment & Publication ---
    "DISHTV": "Media Entertainment & Publication",
    "EROSMEDIA": "Media Entertainment & Publication",
    "INOXLEISUR": "Media Entertainment & Publication",
    "TV18BRDCST": "Media Entertainment & Publication",
    "BCG": "Media Entertainment & Publication",
    # --- Fast Moving Consumer Goods ---
    "GSKCONS": "Fast Moving Consumer Goods", "TATACOFFEE": "Fast Moving Consumer Goods",
    "MCLEODRUSS": "Fast Moving Consumer Goods", "KWALITY": "Fast Moving Consumer Goods",
    "DHAMPURSUG": "Fast Moving Consumer Goods", "UPERGANGES": "Fast Moving Consumer Goods",
    "RUCHI": "Fast Moving Consumer Goods", "VENKEYS": "Fast Moving Consumer Goods",
    "FCONSUMER": "Fast Moving Consumer Goods", "APEX": "Fast Moving Consumer Goods",
    # --- Consumer Services (travel / education / retail / gaming / kiosks) ---
    "COX&KINGS": "Consumer Services", "EASEMYTRIP": "Consumer Services",
    "APTECHT": "Consumer Services", "NIITLTD": "Consumer Services",
    "DELTACORP": "Consumer Services", "FRETAIL": "Consumer Services",
    "FRL": "Consumer Services", "VAKRANGEE": "Consumer Services",
    # --- Consumer Durables ---
    "NILKAMAL": "Consumer Durables", "SYMPHONY": "Consumer Durables",
    "HITACHIHOM": "Consumer Durables", "RAJESHEXPO": "Consumer Durables",
    "RUSHIL": "Construction Materials", "DALMIABHA": "Construction Materials",
    # --- Realty ---
    "HDIL": "Realty", "OMAXE": "Realty", "UNITECH": "Realty",
    # --- Construction ---
    "JPASSOCIAT": "Construction", "SADBHAV": "Construction", "MEP": "Construction",
    "SUNILHITEC": "Construction", "RIIL": "Construction",
    # --- Capital Goods ---
    "PIPAVAVDOC": "Capital Goods", "WALCHANNAG": "Capital Goods",
    "JISLJALEQS": "Capital Goods",
    # --- Power / Utilities ---
    "RELINFRA": "Power", "BFUTILITIE": "Utilities",
    # --- Telecommunication ---
    "RCOM": "Telecommunication", "ONMOBILE": "Telecommunication",
    # --- Services (logistics / airlines) ---
    "GATI": "Services", "SNOWMAN": "Services", "VRLLOG": "Services",
    "JETAIRWAYS": "Services", "SPICEJET": "Services",
    # --- Diversified (genuine multi-segment holding cos) ---
    "ABIRLANUVO": "Diversified", "JAICORPLTD": "Diversified",
    "KESORAMIND": "Diversified",
}
# stray dedupe key from the block above
HAND_SECTOR.pop("IOLCP_DUP", None)

# Judgement calls worth surfacing to the reviewer (business genuinely spans two
# NSE buckets; the chosen label is defensible but not the only option).
SECTOR_JUDGEMENT_CALLS: dict[str, str] = {
    "ABIRLANUVO": "Diversified — was telecom+fashion+financial holdco (→ merged into GRASIM)",
    "KESORAMIND": "Diversified — cement + tyres + rayon; could be Construction Materials",
    "RIIL": "Construction — Reliance Industrial Infrastructure leases pipeline infra; could be Services",
    "RELINFRA": "Power — power distribution + EPC; could be Utilities or Construction",
    "BCG": "Media Entertainment & Publication — Brightcom ad-tech; could be Information Technology",
    "ONMOBILE": "Telecommunication — telecom value-added services; could be Information Technology",
    "MIRZAINT": "Consumer Durables — footwear (Red Tape); NSE files footwear under Consumer Durables",
    "VAKRANGEE": "Consumer Services — e-governance / retail kiosks; could be Information Technology",
    "JISLJALEQS": "Capital Goods — Jain Irrigation micro-irrigation systems + agri-processing",
    "GOACARBON": "Chemicals — calcined petroleum coke; could be Oil Gas & Consumable Fuels",
    "MONSANTO": "Chemicals — agrochemicals + hybrid seeds; could be FMCG",
    "RUSHIL": "Construction Materials — decorative laminates / MDF boards",
}


def _read_nse_file() -> pd.DataFrame | None:
    if not SECTOR_CSV.exists():
        return None
    df = pd.read_csv(SECTOR_CSV)
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns={"ISIN Code": "isin", "Industry": "industry",
                            "Symbol": "symbol"})
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df["isin"] = df["isin"].astype(str).str.strip()
    df["industry"] = df["industry"].astype(str).str.strip()
    return df[["symbol", "isin", "industry"]]


def build_sector_map(
    symbols: list[str], isin_map: dict[str, str]
) -> tuple[dict[str, str], dict]:
    """Return ``{symbol: NSE industry}`` for every symbol, plus a provenance dict.

    Resolution order per symbol:
      1. ISIN join against the NSE current total-market list,
      2. symbol join against the same list,
      3. the hand-classification table,
      4. ``UNKNOWN_SECTOR`` (only the synthetic fixture should reach this).
    """
    nse = _read_nse_file()
    by_isin: dict[str, str] = {}
    by_sym: dict[str, str] = {}
    if nse is not None:
        by_isin = dict(zip(nse["isin"], nse["industry"]))
        by_sym = dict(zip(nse["symbol"], nse["industry"]))

    out: dict[str, str] = {}
    prov = {"isin": [], "symbol": [], "hand": [], "unknown": []}
    for s in symbols:
        isin = isin_map.get(s, "")
        if isin and isin in by_isin:
            out[s], src = by_isin[isin], "isin"
        elif s.upper() in by_sym:
            out[s], src = by_sym[s.upper()], "symbol"
        elif s.upper() in HAND_SECTOR:
            out[s], src = HAND_SECTOR[s.upper()], "hand"
        else:
            out[s], src = UNKNOWN_SECTOR, "unknown"
        prov[src].append(s)

    bad = {s: v for s, v in out.items() if v not in NSE_INDUSTRIES}
    if bad:
        raise AssertionError(
            f"[sectors] {len(bad)} symbol(s) mapped to a non-NSE industry: "
            f"{dict(list(bad.items())[:10])}"
        )

    stats = {
        "n_symbols": len(symbols),
        "by_isin": len(prov["isin"]),
        "by_symbol": len(prov["symbol"]),
        "by_hand": len(prov["hand"]),
        "unknown": len(prov["unknown"]),
        "nse_file_present": nse is not None,
        "unknown_sample": sorted(prov["unknown"])[:20],
        "hand_sample": sorted(prov["hand"])[:20],
        "n_industries_used": len(set(out.values())),
        "judgement_calls": SECTOR_JUDGEMENT_CALLS,
    }
    return out, stats
