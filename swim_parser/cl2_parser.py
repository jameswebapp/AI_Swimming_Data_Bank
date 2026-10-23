from __future__ import annotations

"""
CL2 File Parser for Hy-Tek Meet Manager result files.

Parses the SDIF-based CL2 format to extract meet results.
Based on reverse-engineered field positions from actual CL2 files.

Record types parsed:
    A0 - File header
    B1 - Meet information
    C1 - Team information
    D0 - Individual result
    D3 - Swimmer supplemental info
    G0 - Split times
    Z0 - File terminator
"""
import os
import re
from typing import Optional, Dict, List, Any
from swim_parser.time_utils import parse_time_string, normalize_event_name, parse_course

# Time tokens inside a D0 result block (e.g. "41.15", "1:25.76").
_TIME_TOKEN_RE = re.compile(r"\d{1,2}:\d{2}\.\d{2}|\d{1,3}\.\d{2}")
# DQ / no-show markers, optionally carrying a course suffix ("DQY").
_DQ_TOKEN_RE = re.compile(r"\b(?:DQ|NS|SCR|DFS|DNF)[YLS]?\b")


def _s(line: str, start: int, end: int) -> str:
    """Extract and strip a fixed-width field from a line (0-indexed)."""
    try:
        return line[start:end].strip()
    except IndexError:
        return ""


def parse_cl2_file(filepath: str) -> dict:
    """
    Parse a CL2 file and return structured meet data.
    
    Returns dict with keys:
        meet: dict with meet info
        teams: list of team dicts
        swimmers: list of swimmer dicts (with results nested)
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    
    meet_info = {}
    teams = {}       # team_code -> team dict
    swimmers = {}    # uss_id -> swimmer dict
    current_swimmer_id = None
    current_results = []
    
    current_team_code = ""
    
    for line in lines:
        line = line.rstrip("\n\r")
        if len(line) < 3:
            continue
        
        record_type = line[0:2]
        
        if record_type == "A0":
            meet_info.update(_parse_a0(line))
        elif record_type == "B1":
            meet_info.update(_parse_b1(line))
        elif record_type == "C1":
            team = _parse_c1(line)
            if team and team.get("code"):
                teams[team["code"]] = team
                current_team_code = team["code"]
        elif record_type == "D0":
            result = _parse_d0(line)
            if result:
                # Override team code with the current C1 team if D0 team is blank or just the LSC
                if not result.get("team_code") or result.get("team_code") == result.get("lsc"):
                    result["team_code"] = current_team_code
                
                # Create or update swimmer
                uss_id = result.pop("uss_id", "")
                swimmer_key = uss_id or f"{result.get('last_name', '')}_{result.get('first_name', '')}_{result.get('team_code', '')}"
                
                if swimmer_key not in swimmers:
                    swimmers[swimmer_key] = {
                        "uss_id": uss_id,
                        "first_name": result.pop("first_name", ""),
                        "last_name": result.pop("last_name", ""),
                        "gender": result.pop("gender", ""),
                        "birth_date": result.pop("birth_date", ""),
                        "age": result.pop("age", None),
                        "team_code": result.pop("team_code", ""),
                        "lsc": result.pop("lsc", ""),
                        "results": [],
                    }
                else:
                    # Remove swimmer fields from result
                    for key in ["first_name", "last_name", "gender", "birth_date", "age", "team_code", "lsc"]:
                        result.pop(key, None)
                
                swimmers[swimmer_key]["results"].append(result)
        elif record_type == "D3":
            # Supplemental swimmer info - has full USS ID
            pass  # Already captured in D0
    
    # Convert to output format
    return {
        "source_file": os.path.basename(filepath),
        "file_type": "cl2",
        "meet": meet_info,
        "teams": list(teams.values()),
        "swimmers": list(swimmers.values()),
        "total_results": sum(len(s["results"]) for s in swimmers.values()),
    }


def _parse_a0(line: str) -> dict:
    """Parse A0 (File Description) record."""
    return {
        "file_format": _s(line, 2, 4),      # "1V" = version
        "file_type": _s(line, 11, 31),       # "Meet Results"
        "software": _s(line, 44, 64),        # "WMM 8.0Ee"
    }


def _parse_b1(line: str) -> dict:
    """
    Parse B1 (Meet) record.
    Verified field positions from actual data:
      [10-39]: Meet name (30 chars)
      [40-70]: Facility (30 chars)
      [80-100]: City
      [100-102]: State
      [102-107]: ZIP
      [110-113]: Country
      [120-128]: Start date MMDDYYYY
      [128-136]: End date MMDDYYYY
      [149]: Course code (Y/L/S)
    """
    raw = line
    meet_name = _s(raw, 10, 40)
    facility = _s(raw, 40, 80)
    city = _s(raw, 80, 100)
    state = _s(raw, 100, 102)
    zip_code = _s(raw, 102, 107)
    country = _s(raw, 117, 120)
    # Standard CL2 format for Meet Dates
    start_date_raw = _s(raw, 121, 129)
    end_date_raw = _s(raw, 129, 137)
    start_date = _format_date(start_date_raw)
    end_date = _format_date(end_date_raw)
    
    course_code = _s(raw, 149, 150)
    course = parse_course(course_code) if course_code else "SCY"
    
    return {
        "name": meet_name,
        "facility": facility,
        "city": city,
        "state": state,
        "zip": zip_code,
        "country": country,
        "start_date": start_date,
        "end_date": end_date,
        "course": course,
    }


def _parse_c1(line: str) -> dict:
    """
    Parse C1 (Team ID) record.
    Verified positions:
      [3-5]:   LSC code (MD)
      [5-7]:   LSC again or blank
      [7-11]:  Team code prefix (MD + code)
      [11-41]: Team name (30 chars)
    Example: C11MD      MDASC Annapolis Swim Club
             0123456789...
    """
    lsc = _s(line, 3, 5)
    # Team code: 2-char LSC prefix at 5-7, then short code at 7-11. Usually at 5-11.
    team_abbr = _s(line, 5, 11).strip()
    team_name = _s(line, 11, 41).strip()
    
    # If team abbr is blank, it's often embedded in the first word of the team name
    if not team_abbr and " " in team_name:
        parts = team_name.split(" ", 1)
        # If the first word looks like a team code (e.g., MDASC, YCM, MDCGA)
        if len(parts[0]) <= 6 and parts[0].isupper():
            team_abbr = parts[0]
            team_name = parts[1].strip()

    return {
        "lsc": lsc,
        "code": team_abbr if team_abbr else lsc,
        "name": team_name,
    }


def _parse_d0(line: str) -> Optional[dict]:
    """
    Parse D0 (Individual Event/Result) record.
    
    This is the most important record. Based on observed CL2 data:
    
    Example line:
    D01MD      Adams, Zoe J                2AFC318D8597AUSA0726201211FF  504 83 111110012023   42.70Y                     41.01Y     5 7    29       80004      NN29
    
    Pos 0-1:   "D0"
    Pos 2:     Org code
    Pos 3-5:   LSC
    Pos 11-39: Name (Last, First MI)
    Pos 39-51: USS ID (partial, 12 chars)
    Pos 51:    Citizen code (A=amateur?)
    Pos 52-55: Country (USA)
    Pos 55-63: Birth date (MMDDYYYY)
    Pos 63-65: Age
    Pos 65:    Gender (F/M)
    Pos 66:    Gender (F/M) duplicate?
    Pos 69-72: Distance
    Pos 72:    Stroke code (1-7 or A-G)
    Pos 74-76: Entry/seed time points?
    Pos 77-79: Age range?
    Pos 80-86: Event date (MMDDYYYY)
    Pos 89-97: Seed time (with course suffix)
    Pos 118-126: Finals time (with course suffix)
    Pos 131-133: Heat
    Pos 134-136: Lane
    Pos 140-143: Points
    """
    if len(line) < 130:
        return None
    
    # Extract name
    name_raw = _s(line, 11, 39)
    last_name, first_name, middle = _parse_name(name_raw)
    
    if not last_name:
        return None
    
    # USS ID
    uss_id = _s(line, 39, 51)
    
    # Country and birth date
    country = _s(line, 52, 55)
    birth_date_raw = _s(line, 55, 63)
    birth_date = _format_date(birth_date_raw)
    
    # Age and gender
    age_str = _s(line, 63, 65)
    age = int(age_str) if age_str.isdigit() else None
    gender = _s(line, 65, 66)
    
    # Event info - from data:  "  504" = 50m + stroke 4(Butterfly)
    # "1001" = 100m + stroke 1(Freestyle)
    # Pos 68-71: distance (right-justified 3 chars + stroke 1 char = 4 char field)
    distance_str = _s(line, 68, 71)
    stroke_code = _s(line, 71, 72)
    
    distance = int(distance_str) if distance_str.isdigit() else 0
    event_name, event_code, stroke = normalize_event_name(distance, stroke_code)
    
    # Result times — tokenized, NOT fixed columns.
    #
    # Two D0 layouts exist in real files:
    #   * Timed-final meets: seed @~89, finals @~116.
    #   * Prelim/final meets (championships): seed @~89, prelim @~98,
    #     finals @~116. Reading finals from fixed cols 116-126 on those
    #     files landed on a 1-2 digit field and stored impossible
    #     "finals" of 1.00-4.00 seconds, and lost real finals for
    #     swimmers whose only swim was the prelim.
    #
    # Rule: collect every time token in cols 84-136. A token starting
    # before col 95 is the seed. The result time is the LAST token at
    # col >= 95 — the final when the swimmer has one, otherwise the
    # prelim (that swim is the swimmer's official result of the meet).
    time_block = line[84:136]
    tokens = [(m.start() + 84, m.group())
              for m in _TIME_TOKEN_RE.finditer(time_block)]
    seed_time = None
    finals_time = None
    if tokens:
        if tokens[0][0] < 95:
            seed_time = parse_time_string(tokens[0][1])
            result_tokens = tokens[1:]
        else:
            result_tokens = tokens
        if result_tokens:
            finals_time = parse_time_string(result_tokens[-1][1])

    # DQ / no-show markers can sit anywhere in the time block (e.g.
    # "DQY" immediately after the seed in prelim/final files).
    dq = bool(_DQ_TOKEN_RE.search(line[80:140]))
    if dq:
        finals_time = None

    # Sanity: no real swim is under 5 seconds; anything smaller is a
    # mis-read of a non-time field and must never be stored as a result.
    if finals_time is not None and finals_time < 5:
        finals_time = None
    
    # Heat and lane: |.01Y     5| 7    29  |
    # Pos 127-129: heat, 130-132: lane
    heat_str = _s(line, 127, 129)
    lane_str = _s(line, 130, 132)
    heat = int(heat_str) if heat_str.isdigit() else None
    lane = int(lane_str) if lane_str.isdigit() else None
    
    # Points/place from end of line: |     80004      NN29|
    # Pos 136-140: points, 140-145: place code
    points_str = _s(line, 136, 140)
    points = int(points_str) if points_str.strip().isdigit() else None
    
    # Place encoded in positions 145-149
    place_str = _s(line, 145, 149)
    place = int(place_str) if place_str.strip().isdigit() else None
    
    # Team/LSC
    lsc = _s(line, 3, 5)
    team_code = _s(line, 5, 11).strip() if _s(line, 5, 11).strip() else lsc
    
    return {
        "last_name": last_name,
        "first_name": first_name,
        "uss_id": uss_id,
        "gender": gender,
        "birth_date": birth_date,
        "age": age,
        "team_code": team_code,
        "lsc": lsc,
        "distance": distance,
        "stroke": stroke,
        "stroke_code": stroke_code,
        "event_name": event_name,
        "event_code": event_code,
        "seed_time": seed_time,
        "finals_time": finals_time,
        "heat": heat,
        "lane": lane,
        "points": points,
        "place": place,
        "dq": dq,
    }


def _parse_name(name_raw: str) -> tuple:
    """Parse 'Last, First MI' format."""
    if "," in name_raw:
        parts = name_raw.split(",", 1)
        last_name = parts[0].strip()
        rest = parts[1].strip()
        # Split first name and middle initial
        first_parts = rest.split()
        first_name = first_parts[0] if first_parts else ""
        middle = " ".join(first_parts[1:]) if len(first_parts) > 1 else ""
        return last_name, first_name, middle
    return name_raw.strip(), "", ""


def _format_date(raw: str) -> Optional[str]:
    """Convert MMDDYYYY to YYYY-MM-DD."""
    raw = raw.strip()
    if not raw or len(raw) != 8 or not raw.isdigit():
        return None
    month = raw[0:2]
    day = raw[2:4]
    year = raw[4:8]
    if int(month) < 1 or int(month) > 12:
        return None
    return f"{year}-{month}-{day}"


if __name__ == "__main__":
    import json
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python cl2_parser.py <file.cl2>")
        sys.exit(1)
    
    result = parse_cl2_file(sys.argv[1])
    print(json.dumps(result, indent=2, default=str))
