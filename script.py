#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modine -> Asia Supplier PDF Converter v5
Generates a 2-page Asia supplier datasheet from a Modine PDF:
  Page 1 – specification table with values extracted and transformed
  Page 2 – dimension drawing copied from the Modine PDF, header/notes stripped
"""

import io
import os
import platform
import re
import subprocess

import pdfplumber
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph

PAGE_WIDTH  = 612
PAGE_HEIGHT = 792


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text(modine_pdf_path):
    with pdfplumber.open(modine_pdf_path) as pdf:
        text = pdf.pages[0].extract_text() or ""
    print(f"Extracted {len(text)} characters from page 1")
    return text


def _value_after(text, label_pattern):
    m = re.search(label_pattern + r"\s+([\d.]+)", text, re.IGNORECASE)
    return float(m.group(1)) if m else None


def _text_after(text, label_pattern):
    m = re.search(label_pattern + r"\s+([^\n]+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _extract_cooling_medium(text):
    """
    Извлекает информацию о Cooling medium из текста Modine PDF.
    Правила:
    - Если "Water" -> "Water"
    - Если "Propylene Glycol" с процентом -> "Propylene Glycol / 40%"
    - Другие комбинации -> соединяет через " / "
    """
    # Ищем секцию Cooling medium
    cooling_section = re.search(r"Cooling medium(.+?)(?:Dimensions|Max operation)", text, re.DOTALL | re.IGNORECASE)
    if not cooling_section:
        return "Water"  # По умолчанию

    section_text = cooling_section.group(1)

    # Ищем основной тип охладителя
    water_match = re.search(r"\bWater\b", section_text, re.IGNORECASE)
    propylene_match = re.search(r"Propylene\s+Glycol", section_text, re.IGNORECASE)

    # Ищем процент (например "40%")
    percentage_match = re.search(r"(\d+)\s*%", section_text)
    percentage = percentage_match.group(1) if percentage_match else None

    # Применяем правила
    if water_match and not propylene_match:
        # Только Water
        return "Water"
    elif propylene_match:
        # Propylene Glycol, возможно с процентом
        if percentage:
            return f"Propylene Glycol / {percentage}%"
        else:
            return "Propylene Glycol"
    else:
        return "Water"  # По умолчанию


def extract_parameters(text):
    params = {}

    params["capacity"] = _value_after(text, r"Air.*Capacity") or 0
    params["cooling_medium"] = _extract_cooling_medium(text)

    air_section = re.search(r"Air(.+?)Cooling medium", text, re.DOTALL | re.IGNORECASE)
    if air_section:
        s = air_section.group(1)
        m = re.search(r"Flow\s+rate\s+([\d.]+)", s, re.IGNORECASE)
        if m: params["air_flow"] = float(m.group(1))
        m = re.search(r"Pressure\s+drop\s+([\d.]+)", s, re.IGNORECASE)
        if m: params["air_pressure_drop"] = float(m.group(1))
    params.setdefault("air_flow", 0)
    params.setdefault("air_pressure_drop", 0)

    cooling_section = re.search(r"Cooling medium(.+?)Dimensions", text, re.DOTALL | re.IGNORECASE)
    if cooling_section:
        s = cooling_section.group(1)
        m = re.search(r"Flow\s+rate\s+([\d.]+)", s, re.IGNORECASE)
        if m: params["water_flow"] = float(m.group(1))
        m = re.search(r"Temperature\s+in\s+([\d.]+)", s, re.IGNORECASE)
        if m: params["water_temp_in"] = float(m.group(1))
        m = re.search(r"Pressure\s+drop\s+([\d.]+)", s, re.IGNORECASE)
        if m: params["water_pressure_drop"] = float(m.group(1))
    params.setdefault("water_flow", 0)
    params.setdefault("water_temp_in", 0)
    params.setdefault("water_pressure_drop", 0)

    params["max_op_pressure"]  = _value_after(text, r"Max\s+op\.?\s+pressure") or 0
    params["test_pressure"]    = _value_after(text, r"Test\s+pressure") or 0
    params["max_op_temp"]      = _value_after(text, r"Max\s+op\.?\s+temperature") or 0
    params["abs_pressure"]     = _value_after(text, r"Absolute\s+pressure") or 1013
    params["connection"]       = _text_after(text, r"Connection\s+size") or "TOBE-FILLED"
    params["ordering_code"]    = _text_after(text, r"Ordering\s+code") or "TOBE-FILLED"
    params["fin_material"]     = _text_after(text, r"Fin\s+material") or "TOBE-FILLED"

    print(f"  Capacity [kW]:             {params['capacity']}")
    print(f"  Air flow [m³/s]:           {params['air_flow']}")
    print(f"  Air pressure drop [Pa]:    {params['air_pressure_drop']}")
    print(f"  Water flow [m³/h]:         {params['water_flow']}")
    print(f"  Water temp in [°C]:        {params['water_temp_in']}")
    print(f"  Water pressure drop [kPa]: {params['water_pressure_drop']}")
    print(f"  Max op. pressure [MPa]:    {params['max_op_pressure']}")
    print(f"  Test pressure [MPa]:       {params['test_pressure']}")
    print(f"  Max op. temperature [°C]:  {params['max_op_temp']}")
    print(f"  Absolute pressure [hPa]:   {params['abs_pressure']}")
    print(f"  Connection:                {params['connection']}")
    print(f"  Ordering code:             {params['ordering_code']}")
    print(f"  Cooling medium:            {params['cooling_medium']}")
    print(f"  Fin material:              {params['fin_material']}")
    return params


def apply_transformations(values):
    t = values.copy()
    t["air_pressure_drop"]   = values["air_pressure_drop"]   + 10
    t["water_pressure_drop"] = values["water_pressure_drop"] + 10
    t["max_air_temp_calc"]   = values["water_temp_in"]       + 13
    print(f"  Air pressure drop:   {values['air_pressure_drop']} + 10 = {t['air_pressure_drop']} Pa")
    print(f"  Water pressure drop: {values['water_pressure_drop']} + 10 = {t['water_pressure_drop']} kPa")
    print(f"  Max air temp out:    {values['water_temp_in']} + 13 = {t['max_air_temp_calc']} °C")
    return t


# ---------------------------------------------------------------------------
# Page 1 – specification table
# ---------------------------------------------------------------------------

def _fmt(v, digits=0):
    if v == 0:
        return "TOBE-FILLED"
    return f"{v:.{digits}f}" if digits > 0 else str(int(v))


def _spec_table_data(values):
    water_in     = values["water_temp_in"]
    max_air_temp = values["max_air_temp_calc"]
    temp_text    = f"≤ 13 K (≤ {int(max_air_temp)}°C at {int(water_in)}°C water in)"
    ped_text     = "PED, Pressure Equipment Directive 97/23/EC"

    # Определяем тип охладителя по Ordering code
    ordering_code = values.get("ordering_code", "")
    is_double_tube = "QDKR" in ordering_code.upper()
    is_single_tube = "QLKE" in ordering_code.upper()

    # Определяем значения на основе типа
    if is_double_tube:
        cooler_type = "Double tube"
        secondary_material = "Copper"
        secondary_plate = "Naval brass (CuZn38Sn1)"
    elif is_single_tube:
        cooler_type = "Single tube"
        secondary_material = ""
        secondary_plate = ""
    else:
        cooler_type = "Double tube"  # По умолчанию
        secondary_material = "Copper"
        secondary_plate = "Naval brass (CuZn38Sn1)"

    # Используем извлеченное значение cooling_medium
    cooling_medium = values.get("cooling_medium", "Water")

    return [
        ["Parameter",                                                      "Value"],
        ["Water cooler type",                                              cooler_type],
        ["Cooling medium",                                                 cooling_medium],
        ["",                                                               ""],
        ["Primary tube material (inner)",                                  "Copper-Nickel 90/10"],
        ["Secondary tube material (outer)",                                secondary_material],
        ["Fin material",                                                   values.get("fin_material", "TOBE-FILLED")],
        ["Tube plate material (primary)",                                  "Naval brass (CuZn38Sn1)"],
        ["Tube plate (secondary)",                                         secondary_plate],
        ["Header, removable",                                              "Rilsan coated steel"],
        ["Casing material",                                                "Galvanized steel"],
        ["Connection",                                                     values["connection"]],
        ["Designed and manufactured according to",                         ped_text],
        ["",                                                               ""],
        ["Max operation pressure [MPa]",                                   _fmt(values["max_op_pressure"], 1)],
        ["Test pressure [MPa]",                                            _fmt(values["test_pressure"],   1)],
        ["Water temperature in [°C]",                                 _fmt(values["water_temp_in"])],
        ["Max water pressure drop [kPa]",                                  _fmt(values["water_pressure_drop"])],
        ["Cooling capacity [kW]",                                          _fmt(values["capacity"])],
        ["Air flow rate [m³/s]",                                      _fmt(values["air_flow"],        1)],
        ["Max air pressure drop [Pa]",                                     _fmt(values["air_pressure_drop"])],
        ["Absolute pressure [hPa]",                                        _fmt(values["abs_pressure"])],
        ["Water flow rate [m³/h]",                                    _fmt(values["water_flow"],      1)],
        ["Max air temperature out above water temperature in [deg K]",     temp_text],
        ["Internal Fouling Factor [m²K/kW]",                         ""],
        ["Minimum tube thickness [mm]",                                    "Manufacturer default"],
        ["Corrosion allowance in header boxes [mm]",                       "1.5"],
        ["Max operation temperature [°C]",                            _fmt(values["max_op_temp"])],
        ["Other requirements",                                         ""],
    ]


def generate_spec_page(output_path, values, project_id):
    doc = SimpleDocTemplate(output_path, pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
                            leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("T", parent=styles["Heading1"], fontSize=13,
                                 textColor=colors.black, spaceAfter=3,
                                 alignment=TA_LEFT, fontName="Helvetica-Bold")
    proj_style  = ParagraphStyle("P", parent=styles["Normal"], fontSize=12,
                                 alignment=TA_LEFT, spaceAfter=12,
                                 fontName="Helvetica-Bold")

    table = Table(_spec_table_data(values), colWidths=[100*mm, 70*mm])
    table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#6764f6")),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f0f0")]),
        ("GRID",          (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    doc.build([
        Paragraph("Specification sheet for water cooler", title_style),
        Paragraph(f"Project nr: {project_id}", proj_style),
        table,
    ])
    print("  Specification page generated")


# ---------------------------------------------------------------------------
# Page 2 – dimension drawing (cleaned)
# ---------------------------------------------------------------------------

def _white_overlay(areas):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c.setFillColorRGB(1, 1, 1)
    c.setStrokeColorRGB(1, 1, 1)
    for (x0, y0, x1, y1) in areas:
        c.rect(x0, y0, x1 - x0, y1 - y0, fill=1, stroke=0)
    c.save()
    buf.seek(0)
    return buf


def append_drawing_page(asia_pdf_path, modine_pdf_path):
    # All coordinates are PDF native (bottom-up, origin = bottom-left corner).
    # Regions to erase from the Modine page 2:
    #   • Top strip (top 62 pts):  Modine logo image + date
    #   • Right-side block:        material specs (Flange, Fin pitch … Max Op.temp)
    #   • Bottom-left label:       "Design code version g = 1 / QDKR - PRELIMINARY"
    white_areas = [
        (0,   PAGE_HEIGHT - 72, PAGE_WIDTH, PAGE_HEIGHT),  # logo + date
        (365, 127,               PAGE_WIDTH, 302),          # material specs block
        (0, 	0,		PAGE_WIDTH, 162),		# design code label
    ]

    overlay   = PdfReader(_white_overlay(white_areas))
    modine    = PdfReader(modine_pdf_path)
    drawing   = modine.pages[1]
    drawing.merge_page(overlay.pages[0])

    asia      = PdfReader(asia_pdf_path)
    writer    = PdfWriter()
    for page in asia.pages:
        writer.add_page(page)
    writer.add_page(drawing)

    with open(asia_pdf_path, "wb") as f:
        writer.write(f)
    print("  Drawing page appended")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def find_modine_files(directory="."):
    return sorted(f for f in os.listdir(directory)
                  if f.lower().endswith(".pdf") and "modine" in f.lower())


def project_id_from_filename(path):
    m = re.search(r"(\d{4}[A-Z]{2}\d{3})", os.path.basename(path))
    return m.group(1) if m else "TOBE-FILLED"


def open_pdf(file_path):
    try:
        if platform.system() == "Darwin":
            subprocess.Popen(["open", file_path])
        elif platform.system() == "Windows":
            for editor in [
                r"C:\Program Files\Tracker Software\PDF Editor\PDFXEdit.exe",
                r"C:\Program Files (x86)\Tracker Software\PDF Editor\PDFXEdit.exe",
                r"C:\Program Files\Tracker Software\PDF Viewer\PDFXEdit.exe",
            ]:
                if os.path.exists(editor):
                    subprocess.Popen([editor, file_path])
                    return
            os.startfile(file_path)
        else:
            subprocess.Popen(["xdg-open", file_path])
    except Exception as e:
        print(f"Warning: could not open PDF viewer: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("MODINE -> ASIA SUPPLIER PDF CONVERTER  v5  (2-page)")
    print("=" * 70)

    modine_files = find_modine_files()
    if not modine_files:
        print('ERROR: no PDF file with "Modine" in the name found.')
        return

    if len(modine_files) == 1:
        selected = modine_files[0]
        print(f"\nFound: {selected}")
    else:
        print("\nMultiple Modine files found:")
        for i, f in enumerate(modine_files, 1):
            print(f"  {i}. {f}")
        choice = input(f"Select file (1-{len(modine_files)}): ")
        try:
            selected = modine_files[int(choice) - 1]
        except (ValueError, IndexError):
            print("ERROR: invalid choice")
            return

    output = os.path.splitext(selected)[0].replace("Modine", "Asia") + ".pdf"
    print(f"Output:  {output}\n")

    print("Reading Modine PDF...")
    text       = extract_text(selected)
    project_id = project_id_from_filename(selected)
    print(f"Project ID: {project_id}\n")

    print("Extracting parameters...")
    params      = extract_parameters(text)
    print("\nApplying transformations...")
    transformed = apply_transformations(params)

    print("\nGenerating specification page (page 1)...")
    generate_spec_page(output, transformed, project_id)

    print("Appending drawing page (page 2)...")
    append_drawing_page(output, selected)

    open_pdf(output)

    print("\n" + "=" * 70)
    print("Done — 2-page Asia supplier PDF ready!")
    print("=" * 70)


if __name__ == "__main__":
    main()