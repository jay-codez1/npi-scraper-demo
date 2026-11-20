"""Clean, validate and export the scraped registry records to Excel plus a quality report."""

import argparse
import json
import re
import sqlite3
from collections import Counter

from openpyxl import Workbook
from openpyxl.styles import Font

COLUMNS = [
    "npi",
    "provider_type",
    "status",
    "name",
    "first_name",
    "middle_name",
    "last_name",
    "credential",
    "organization_name",
    "sole_proprietor",
    "enumeration_date",
    "last_updated",
    "phone",
    "fax",
    "secondary_phone",
    "authorized_official_phone",
    "practice_address_1",
    "practice_address_2",
    "practice_city",
    "practice_state",
    "practice_zip",
    "practice_zip4",
    "mailing_address_1",
    "mailing_address_2",
    "mailing_city",
    "mailing_state",
    "mailing_zip",
    "mailing_phone",
    "primary_specialty",
    "primary_taxonomy_code",
    "license_number",
    "license_state",
    "all_specialties",
    "other_names",
    "authorized_official",
    "authorized_official_title",
    "email_endpoints",
    "website_endpoints",
    "npi_checksum_valid",
]


def clean(value):
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return "" if text in ("--", "N/A") else text


def phone(value):
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10 or len(set(digits)) == 1:
        return ""
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def npi_valid(npi):
    """NPIs carry a Luhn check digit computed over the prefix 80840 + the number."""
    if not re.fullmatch(r"\d{10}", npi):
        return False
    total = 0
    for i, ch in enumerate(reversed("80840" + npi)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def address(rec, purpose):
    return next(
        (a for a in rec.get("addresses", []) if a.get("address_purpose") == purpose), {}
    )


def to_row(rec):
    basic = rec.get("basic", {})
    loc, mail = address(rec, "LOCATION"), address(rec, "MAILING")
    taxonomies = rec.get("taxonomies", [])
    primary = next(
        (t for t in taxonomies if t.get("primary")), taxonomies[0] if taxonomies else {}
    )
    is_person = rec.get("enumeration_type") == "NPI-1"
    person = " ".join(
        filter(
            None,
            (clean(basic.get(k)) for k in ("first_name", "middle_name", "last_name")),
        )
    )
    zip_digits = re.sub(r"\D", "", loc.get("postal_code") or "")
    mail_digits = re.sub(r"\D", "", mail.get("postal_code") or "")
    main_phone = phone(loc.get("telephone_number"))
    extra_phones = []
    for pl in rec.get("practiceLocations", []):
        p = phone(pl.get("telephone_number"))
        if p and p != main_phone and p not in extra_phones:
            extra_phones.append(p)
    endpoints = rec.get("endpoints", [])
    emails = sorted(
        {
            clean(e.get("endpoint"))
            for e in endpoints
            if "@" in (e.get("endpoint") or "")
        }
    )
    sites = sorted(
        {
            clean(e.get("endpoint"))
            for e in endpoints
            if (e.get("endpoint") or "").lower().startswith("http")
        }
    )
    official = " ".join(
        filter(
            None,
            (
                clean(basic.get(f"authorized_official_{k}"))
                for k in ("first_name", "last_name")
            ),
        )
    )
    npi = str(rec["number"])
    return {
        "npi": npi,
        "provider_type": "Individual" if is_person else "Organization",
        "status": {"A": "Active"}.get(basic.get("status"), clean(basic.get("status"))),
        "name": person if is_person else clean(basic.get("organization_name")),
        "first_name": clean(basic.get("first_name")),
        "middle_name": clean(basic.get("middle_name")),
        "last_name": clean(basic.get("last_name")),
        "credential": clean(basic.get("credential")),
        "organization_name": clean(basic.get("organization_name")),
        "sole_proprietor": clean(basic.get("sole_proprietor")),
        "enumeration_date": clean(basic.get("enumeration_date")),
        "last_updated": clean(basic.get("last_updated")),
        "phone": main_phone,
        "fax": phone(loc.get("fax_number")),
        "secondary_phone": "; ".join(extra_phones),
        "authorized_official_phone": phone(
            basic.get("authorized_official_telephone_number")
        ),
        "practice_address_1": clean(loc.get("address_1")),
        "practice_address_2": clean(loc.get("address_2")),
        "practice_city": clean(loc.get("city")).title(),
        "practice_state": clean(loc.get("state")),
        "practice_zip": zip_digits[:5],
        "practice_zip4": zip_digits[5:9],
        "mailing_address_1": clean(mail.get("address_1")),
        "mailing_address_2": clean(mail.get("address_2")),
        "mailing_city": clean(mail.get("city")).title(),
        "mailing_state": clean(mail.get("state")),
        "mailing_zip": mail_digits[:5],
        "mailing_phone": phone(mail.get("telephone_number")),
        "primary_specialty": clean(primary.get("desc")),
        "primary_taxonomy_code": clean(primary.get("code")),
        "license_number": clean(primary.get("license")),
        "license_state": clean(primary.get("state")),
        "all_specialties": "; ".join(
            dict.fromkeys(clean(t.get("desc")) for t in taxonomies if t.get("desc"))
        ),
        "other_names": "; ".join(
            dict.fromkeys(
                clean(o.get("organization_name"))
                or clean(f"{o.get('first_name', '')} {o.get('last_name', '')}")
                for o in rec.get("other_names", [])
            )
        ),
        "authorized_official": official,
        "authorized_official_title": clean(
            basic.get("authorized_official_title_or_position")
        ),
        "email_endpoints": "; ".join(emails),
        "website_endpoints": "; ".join(sites),
        "npi_checksum_valid": "Yes" if npi_valid(npi) else "No",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/npi.sqlite")
    ap.add_argument("--state", default="TX")
    ap.add_argument("--zip-prefixes", nargs="+", required=True)
    ap.add_argument("--xlsx", default="output/npi_registry_houston_area.xlsx")
    ap.add_argument("--report", default="output/quality_report.md")
    ap.add_argument(
        "--sample",
        type=int,
        default=0,
        help="export only the first N records (pilot file)",
    )
    args = ap.parse_args()

    db = sqlite3.connect(args.db)
    raw_total = db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    parts = dict(db.execute("SELECT status, COUNT(*) FROM partitions GROUP BY status"))
    fetched_rows = db.execute(
        "SELECT COALESCE(SUM(fetched), 0) FROM partitions"
    ).fetchone()[0]

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Providers")
    ws.freeze_panes = "A2"
    for i, col in enumerate(COLUMNS):
        ws.column_dimensions[
            chr(65 + i) if i < 26 else "A" + chr(65 + i - 26)
        ].width = max(14, len(col) + 2)
    ws.append(COLUMNS)

    stats, cities, specialties = Counter(), Counter(), Counter()
    out_of_scope = 0
    prefixes = tuple(args.zip_prefixes)
    for (payload,) in db.execute("SELECT payload FROM records ORDER BY npi"):
        row = to_row(json.loads(payload))
        if row["practice_state"] != args.state or not row["practice_zip"].startswith(
            prefixes
        ):
            out_of_scope += 1
            continue
        if args.sample and stats["total"] >= args.sample:
            break
        ws.append([row[c] for c in COLUMNS])
        has_phone, has_email = bool(row["phone"]), bool(row["email_endpoints"])
        stats["total"] += 1
        stats["individual"] += row["provider_type"] == "Individual"
        stats["phone"] += has_phone
        stats["fax"] += bool(row["fax"])
        stats["email"] += has_email
        stats["phone_and_email"] += has_phone and has_email
        stats["no_contact"] += not (has_phone or has_email or row["fax"])
        stats["license"] += bool(row["license_number"])
        stats["bad_checksum"] += row["npi_checksum_valid"] == "No"
        stats["missing_name"] += not row["name"]
        cities[row["practice_city"]] += 1
        specialties[row["primary_specialty"] or "(none listed)"] += 1

    total = stats["total"]
    pct = lambda n: f"{n:,} ({n / total:.1%})" if total else "0"
    summary = [
        (
            "Scope",
            f"{args.state}, practice postal codes starting {', '.join(prefixes)}",
        ),
        ("Records exported (one row per NPI)", f"{total:,}"),
        ("Individuals", pct(stats["individual"])),
        ("Organizations", pct(total - stats["individual"])),
        ("With practice phone", pct(stats["phone"])),
        ("With fax", pct(stats["fax"])),
        ("With email endpoint", pct(stats["email"])),
        ("With both phone and email", pct(stats["phone_and_email"])),
        ("With no contact information", pct(stats["no_contact"])),
        ("With license number", pct(stats["license"])),
        ("Missing name", f"{stats['missing_name']:,}"),
        ("Failed NPI checksum", f"{stats['bad_checksum']:,}"),
        ("Duplicate NPIs in export", "0 (NPI is the primary key)"),
        ("Distinct cities", f"{len(cities):,}"),
    ]
    run = [
        ("Raw unique records in checkpoint database", f"{raw_total:,}"),
        ("Rows received from the API (before de-duplication)", f"{fetched_rows:,}"),
        ("Dropped as outside scope", f"{out_of_scope:,}"),
        ("Partitions fully fetched", f"{parts.get('done', 0):,}"),
        ("Partitions split into smaller ones", f"{parts.get('split', 0):,}"),
        ("Partitions truncated by the API cap", f"{parts.get('truncated', 0):,}"),
        ("Partitions still pending", f"{parts.get('pending', 0):,}"),
    ]

    sheet = wb.create_sheet("Summary")
    sheet.column_dimensions["A"].width = 52
    sheet.column_dimensions["B"].width = 44
    bold = Font(bold=True)
    for title, rows in (("Data quality", summary), ("Extraction run", run)):
        sheet.append([title])
        sheet.append([])
        for label, value in rows:
            sheet.append([label, value])
        sheet.append([])
    sheet.append(["Top 25 cities", "Records"])
    for city, n in cities.most_common(25):
        sheet.append([city, n])
    sheet.append([])
    sheet.append(["Top 25 primary specialties", "Records"])
    for spec, n in specialties.most_common(25):
        sheet.append([spec, n])
    wb.save(args.xlsx)

    if args.report:
        lines = [
            "# Data quality and completeness report",
            "",
            "## Data quality",
            "",
            "| Metric | Value |",
            "|---|---|",
        ]
        lines += [f"| {a} | {b} |" for a, b in summary]
        lines += ["", "## Extraction run", "", "| Metric | Value |", "|---|---|"]
        lines += [f"| {a} | {b} |" for a, b in run]
        lines += ["", "## Top 15 cities", "", "| City | Records |", "|---|---|"]
        lines += [f"| {c} | {n:,} |" for c, n in cities.most_common(15)]
        with open(args.report, "w") as fh:
            fh.write("\n".join(lines) + "\n")
    print("\n".join(f"{a}: {b}" for a, b in summary + run))


if __name__ == "__main__":
    main()
