"""Indian GST state codes.

Pure data and two lookups, no I/O. The first two characters of a GSTIN are the
state code issued by the GST Network, so a registration's state is **derivable**
from the GSTIN itself and is never asked for: a form that let someone type
"Maharashtra" against a GSTIN beginning ``29`` would invite a record that
contradicts itself.

Why a static list rather than a table
------------------------------------
These codes change when India changes — a union territory merges, a new one is
created — which has happened twice in a decade and is a code change either way,
because the merge also has to say what happens to the registrations already
recorded. A settings table would imply an administrator can edit them, and an
administrator editing the meaning of ``26`` would silently relabel every existing
branch in Dadra and Nagar Haveli. So: a constant here, changed deliberately.

**An unknown code is kept, not rejected.** ``ck_exporter_gstin_format`` accepts any
two digits, so rows with a code absent from this list already exist and more can
arrive from a GSTIN that is valid but whose code we have not listed. Those keep
``state_name = NULL``, which reads as "we do not know this state" — honest, and
visible on a report — rather than being refused at the point where someone is
trying to record a real registration.

Source: GST Network's state-code list. ``97`` (Other Territory) and ``99``
(Centre Jurisdiction) are administrative rather than geographic and are included
because registrations really carry them.
"""

from __future__ import annotations

#: GST state code → the state's name as the GST portal prints it.
GST_STATE_NAMES: dict[str, str] = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    # 25 was Daman and Diu, merged into 26 in 2020. Kept so a registration issued
    # before the merge still reads with a state rather than as unknown.
    "25": "Daman and Diu (merged into Dadra and Nagar Haveli and Daman and Diu)",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "28": "Andhra Pradesh (before the 2014 reorganisation)",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "97": "Other Territory",
    "99": "Centre Jurisdiction",
}


def state_code_of(gstin: str | None) -> str | None:
    """The first two characters of a GSTIN, or ``None`` if it has none.

    Takes the characters as they are rather than validating the whole GSTIN:
    ``ck_exporter_gstin_format`` and ``normalise_gstins`` own the format, and this
    is used by a migration over rows that are already stored.
    """
    cleaned = (gstin or "").strip()
    if len(cleaned) < 2 or not cleaned[:2].isdigit():
        return None
    return cleaned[:2]


def state_name_of(gstin: str | None) -> str | None:
    """The state a GSTIN was issued in, or ``None`` for a code not in the list
    (module docstring: unknown is recorded as unknown, never guessed)."""
    code = state_code_of(gstin)
    return GST_STATE_NAMES.get(code) if code else None


__all__ = ["GST_STATE_NAMES", "state_code_of", "state_name_of"]
