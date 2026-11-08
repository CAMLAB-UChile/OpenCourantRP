"""About text (keep in sync with installer/OpenCourantRP.iss)."""

TITLE = "OpenCourantRP"
SUBTITLE = "Run and Post-processor tool for the explicit finite element solver OpenCourant"
LICENSE_LINE = "License AGPL-3.0 or later"
COPYRIGHT = "Copyright 2026 Alejandro Ortiz-Bernardin"
URL = "https://camlab.cl/software/OpenCourantRP/"


def about_html(version: str) -> str:
    return (
        f"<h2>{TITLE}</h2>"
        f"<p style='color:gray'>Version {version}</p>"
        f"<p>{SUBTITLE}</p>"
        f"<p>{LICENSE_LINE}<br>{COPYRIGHT}<br><a href='{URL}'>{URL}</a></p>"
    )
