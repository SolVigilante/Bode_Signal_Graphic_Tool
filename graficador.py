#!/usr/bin/env python3
"""
overlay_csv.py — Superpone N archivos CSV (dos o más) para comparar:
  - Diagramas de Bode (magnitud [dB] y fase [deg] vs frecuencia)
  - Señales de osciloscopio / transitorios (amplitud vs tiempo)

Si un mismo archivo trae más de una señal (ej. un osciloscopio con
CH1/CH2/CH3/CH4, o un export de LTSpice con varias V(nodo)), el script
las detecta automáticamente y las grafica todas — no hace falta separar
los CSV a mano.

Pensado para archivos que vienen de:
  - Osciloscopios (Tektronix, Rigol, Keysight, etc.) — suelen traer filas de
    metadata antes de los datos, y nombres de columnas variables.
  - LTSpice (File > Export Data as Text) — separado por tabs, con columnas
    tipo "Freq." / "V(nodo)" (a veces como número complejo "(dB,fase)",
    con la unidad pegada al número, ej. "-3.9e-04dB,-5.4e-01°").

Uso típico (2 o más archivos, sin límite; cada uno puede traer varias señales):
    python overlay_csv.py bode medido.csv sim1.csv sim2.csv \
        --labels "Medición" "LTSpice R=1k" "LTSpice R=2k" --title "Bode - Filtro RLC"

    python overlay_csv.py signal ch1234.csv otro.csv \
        --labels "Osciloscopio" "Referencia" --title "Osciloscopio"

Si el autodetect de columnas falla, se puede forzar todo a mano con
--time-col / --volt-col / --freq-col / --mag-col / --phase-col
(nombre o índice de columna — aplica igual a todos los archivos, y fuerza
una sola señal por archivo en vez de la detección múltiple).
"""

import argparse
import csv
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


# --------------------------------------------------------------------------
# Carga robusta de CSV: detecta delimitador y salta filas de metadata
# --------------------------------------------------------------------------

def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        # fallback: el que más aparezca en la primera línea
        first_line = sample.splitlines()[0] if sample.splitlines() else ","
        counts = {d: first_line.count(d) for d in [",", ";", "\t"]}
        return max(counts, key=counts.get)


def _is_numeric_row(fields):
    ok = 0
    for f in fields:
        f = f.strip()
        if _to_complex_or_float(f) is not None:
            ok += 1
    return ok >= max(1, len(fields) - 1)  # tolera 1 columna no numérica (ej. texto)


def load_csv(path, delimiter=None, skiprows=None):
    """
    Devuelve (header: list[str], rows: list[list[str]])
    Detecta automáticamente el delimitador y descarta líneas de metadata
    previas a la fila de encabezado real (típico de exports de osciloscopio).
    """
    path = Path(path)
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")  # típico en exports de LTSpice/osciloscopio (° mal codificado en UTF-8)
    lines = [l for l in text.splitlines() if l.strip() != ""]
    if not lines:
        raise ValueError(f"{path} está vacío")

    if delimiter is None:
        delimiter = _sniff_delimiter("\n".join(lines[:5]))

    reader = list(csv.reader(lines, delimiter=delimiter))

    if skiprows is not None:
        header = reader[skiprows]
        data_rows = reader[skiprows + 1:]
        return [h.strip() for h in header], data_rows

    # Autodetección: la fila de encabezado es la última fila NO numérica
    # antes de que empiecen filas numéricas.
    header_idx = 0
    for i, row in enumerate(reader):
        if _is_numeric_row(row):
            header_idx = max(0, i - 1)
            break
    else:
        header_idx = 0

    header = [h.strip() for h in reader[header_idx]]
    data_rows = reader[header_idx + 1:]
    data_rows = [r for r in data_rows if len(r) == len(header) and _is_numeric_row(r)]
    return header, data_rows


# --------------------------------------------------------------------------
# Parsing de valores (soporta números normales y complejos estilo LTSpice)
# --------------------------------------------------------------------------

_complex_re = re.compile(
    r"^\(?\s*(-?[\d.eE+-]+)\s*[A-Za-zÀ-ÿ°Ω%]*\s*,\s*(-?[\d.eE+-]+)\s*[A-Za-zÀ-ÿ°Ω%]*\s*\)?$"
)


def _to_complex_or_float(s):
    s = s.strip()
    if s == "":
        return None
    m = _complex_re.match(s)
    if m:
        try:
            return (float(m.group(1)), float(m.group(2)))  # (mag_dB o real, fase o imag)
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _find_col(header, name_hint_list, index_override=None):
    if index_override is not None:
        try:
            return int(index_override)
        except ValueError:
            index_override_lower = index_override.lower()
            for i, h in enumerate(header):
                if h.lower() == index_override_lower:
                    return i
            raise ValueError(f"No se encontró la columna '{index_override}'")

    lower = [h.lower() for h in header]
    for hint in name_hint_list:
        for i, h in enumerate(lower):
            if hint in h:
                return i
    return None


_INDEX_LIKE = {"#", "index", "no", "no.", "n", "n.", "muestra", "sample", "pt", "point", "idx"}


def _find_cols_all(header, name_hint_list, exclude=()):
    """Todos los índices de columna cuyo nombre matchea alguno de los hints, en orden."""
    lower = [h.lower().strip() for h in header]
    out = []
    for i, h in enumerate(lower):
        if i in exclude:
            continue
        if any(hint in h for hint in name_hint_list):
            out.append(i)
    return out


# --------------------------------------------------------------------------
# Extracción de datasets
# --------------------------------------------------------------------------

def extract_signal(header, rows, time_col=None, volt_col=None):
    """
    Devuelve una lista de (label, t, v) — una por cada señal encontrada
    en el archivo. Si volt_col se especifica a mano, devuelve una sola.
    """
    ti = _find_col(header, ["time", "tiempo", "x-axis", "sec"], time_col)
    if ti is None:
        ti = 0

    if volt_col is not None:
        vi = _find_col(header, ["ch1", "ch2", "v(", "volt", "y-axis", "ampl"], volt_col)
        volt_idxs = [vi]
    else:
        # Todas las columnas menos la de tiempo (y columnas tipo índice) son señales.
        volt_idxs = [
            i for i, h in enumerate(header)
            if i != ti and h.strip().lower() not in _INDEX_LIKE
        ]
        if not volt_idxs:
            volt_idxs = [1 if len(header) > 1 else 0]

    traces = []
    for vi in volt_idxs:
        t, v = [], []
        for r in rows:
            if vi >= len(r):
                continue
            tv = _to_complex_or_float(r[ti])
            vv = _to_complex_or_float(r[vi])
            if isinstance(tv, float) and isinstance(vv, float):
                t.append(tv)
                v.append(vv)
        if t:
            traces.append((header[vi] if vi < len(header) else f"col{vi}", np.array(t), np.array(v)))
    return traces


def extract_bode(header, rows, freq_col=None, mag_col=None, phase_col=None, mag_is_db=True):
    """
    Devuelve una lista de (label, freq, mag, phase) — una por cada traza
    de Bode encontrada en el archivo. Detecta automáticamente:
      - columnas de valor complejo por trace, ej. "V(nodo)" estilo LTSpice
        con celdas tipo "(mag,fase)"
      - pares de columnas Gain/Phase (o Mag/Phase) por nombre, en orden
    Si mag_col o phase_col se especifican a mano, devuelve una sola traza.
    """
    fi = _find_col(header, ["freq", "frecuencia", "hz"], freq_col)
    if fi is None:
        fi = 0

    if mag_col is not None or phase_col is not None:
        mi = _find_col(header, ["v(", "i(", "db(", "mag", "gain", "amplitud"], mag_col)
        pi = _find_col(header, ["phase", "fase", "deg", "ang"], phase_col)
        return [_extract_bode_single(header, rows, fi, mi, pi, mag_is_db)]

    n_cols = len(header)
    other_idxs = [i for i in range(n_cols) if i != fi]

    # 1) Columnas de valor complejo (una traza cada una), detectado por dato real
    complex_idxs = []
    for i in other_idxs:
        sample = next((r[i] for r in rows if i < len(r) and r[i].strip() != ""), None)
        if sample is not None and isinstance(_to_complex_or_float(sample), tuple):
            complex_idxs.append(i)

    traces = []
    for i in complex_idxs:
        label = header[i] if i < len(header) else f"col{i}"
        traces.append(_extract_bode_single(header, rows, fi, i, None, mag_is_db))

    # 2) Pares Gain/Phase por nombre (excluyendo lo ya usado como complejo)
    remaining = [i for i in other_idxs if i not in complex_idxs]
    mag_idxs = _find_cols_all(header, ["db", "gain", "mag"], exclude=set(range(n_cols)) - set(remaining))
    phase_idxs = _find_cols_all(header, ["phase", "fase", "deg", "ang"], exclude=set(range(n_cols)) - set(remaining))

    for mi, pi in zip(mag_idxs, phase_idxs):
        traces.append(_extract_bode_single(header, rows, fi, mi, pi, mag_is_db))

    # 3) Fallback: si no se detectó nada y sobran exactamente 2 columnas simples
    if not traces:
        leftover = [i for i in remaining if i not in mag_idxs and i not in phase_idxs]
        if len(leftover) >= 2:
            traces.append(_extract_bode_single(header, rows, fi, leftover[0], leftover[1], mag_is_db))
        elif len(remaining) >= 2:
            traces.append(_extract_bode_single(header, rows, fi, remaining[0], remaining[1], mag_is_db))

    return traces


def _extract_bode_single(header, rows, fi, mi, pi, mag_is_db):
    label = header[mi] if mi is not None and mi < len(header) else "Bode"
    freq, mag, phase = [], [], []
    for r in rows:
        fv = _to_complex_or_float(r[fi]) if fi < len(r) else None
        if not isinstance(fv, float):
            continue

        # Caso LTSpice: una sola columna compleja "(dB, fase)" para V(nodo)
        if mi is not None and pi is None and mi < len(r):
            val = _to_complex_or_float(r[mi])
            if isinstance(val, tuple):
                freq.append(fv)
                mag.append(val[0])
                phase.append(val[1])
                continue

        mv = _to_complex_or_float(r[mi]) if mi is not None and mi < len(r) else None
        pv = _to_complex_or_float(r[pi]) if pi is not None and pi < len(r) else None

        if isinstance(mv, tuple):  # columna de magnitud también viene compleja
            mv, pv2 = mv
            pv = pv if isinstance(pv, float) else pv2

        if isinstance(mv, float):
            freq.append(fv)
            mag.append(mv if mag_is_db else 20 * np.log10(abs(mv) + 1e-30))
            phase.append(pv if isinstance(pv, float) else np.nan)

    return (label, np.array(freq), np.array(mag), np.array(phase))


# --------------------------------------------------------------------------
# Plots
# --------------------------------------------------------------------------

def _colors_for(n):
    if n <= 10:
        return None  # usa el ciclo de colores default de matplotlib
    return [plt.cm.turbo(i / max(1, n - 1)) for i in range(n)]


def plot_signal(traces, title, style, save):
    plt.style.use("dark_background" if style == "dark" else "default")
    fig, ax = plt.subplots(figsize=(9, 5))
    colors = _colors_for(len(traces))
    for i, (lbl, t, v) in enumerate(traces):
        kwargs = {"color": colors[i]} if colors else {}
        ax.plot(t, v, label=lbl, linewidth=1.4, **kwargs)
    ax.set_xlabel("Tiempo [s]")
    ax.set_ylabel("Amplitud [V]")
    ax.set_title(title or "Superposición de señales")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    _finish(fig, save)


def plot_bode(traces, title, style, save):
    plt.style.use("dark_background" if style == "dark" else "default")
    fig, (ax_mag, ax_phase) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    colors = _colors_for(len(traces))
    for i, (lbl, f, m, p) in enumerate(traces):
        kwargs = {"color": colors[i]} if colors else {}
        ax_mag.semilogx(f, m, label=lbl, linewidth=1.4, **kwargs)
        ax_phase.semilogx(f, p, label=lbl, linewidth=1.4, **kwargs)
    ax_mag.set_ylabel("Magnitud [dB]")
    ax_mag.grid(True, which="both", alpha=0.3)
    ax_mag.legend()
    ax_mag.set_title(title or "Diagrama de Bode")

    ax_phase.set_ylabel("Fase [°]")
    ax_phase.set_xlabel("Frecuencia [Hz]")
    ax_phase.grid(True, which="both", alpha=0.3)
    ax_phase.legend()

    fig.tight_layout()
    _finish(fig, save)


def _finish(fig, save):
    if save:
        fig.savefig(save, dpi=150)
        print(f"Guardado: {save}")
    else:
        plt.show()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Superpone N CSV (Bode o señales de osciloscopio).")
    p.add_argument("mode", choices=["bode", "signal"], help="Tipo de gráfico")
    p.add_argument("files", nargs="+", metavar="archivo.csv",
                    help="Dos o más archivos CSV a superponer")
    p.add_argument("--labels", nargs="+", default=None, metavar="LABEL",
                    help="Un label por ARCHIVO (no por señal), en el mismo orden. "
                         "Si un archivo trae varias señales, se les agrega el nombre "
                         "de columna automáticamente (ej. 'Osciloscopio – CH2'). "
                         "Si se omite, usa el nombre del archivo.")
    p.add_argument("--title", default=None)
    p.add_argument("--style", choices=["white", "dark"], default="white")
    p.add_argument("--save", default=None, help="Ruta de salida (png). Si no se pasa, muestra la figura.")
    p.add_argument("--delimiter", default=None, help="Forzar delimitador (',', ';', '\\t')")
    p.add_argument("--skiprows", type=int, default=None, help="Forzar índice de fila de encabezado (0-based)")

    # overrides de columnas (nombre o índice), aplican a todos los archivos
    p.add_argument("--time-col", default=None)
    p.add_argument("--volt-col", default=None)
    p.add_argument("--freq-col", default=None)
    p.add_argument("--mag-col", default=None)
    p.add_argument("--phase-col", default=None)
    p.add_argument("--mag-linear", action="store_true",
                    help="La columna de magnitud viene en escala lineal, no en dB")

    args = p.parse_args()

    if len(args.files) < 2:
        p.error("Hay que pasar al menos dos archivos CSV para superponer.")
    if args.labels and len(args.labels) != len(args.files):
        p.error(f"Pasaste {len(args.files)} archivos pero {len(args.labels)} labels; tienen que coincidir.")

    file_labels = args.labels or [Path(f).stem for f in args.files]

    all_traces = []  # lista plana: (label, ...arrays...)
    for f, file_label in zip(args.files, file_labels):
        header, rows = load_csv(f, delimiter=args.delimiter, skiprows=args.skiprows)
        if args.mode == "signal":
            per_file = extract_signal(header, rows, args.time_col, args.volt_col)
        else:
            per_file = extract_bode(
                header, rows, args.freq_col, args.mag_col, args.phase_col,
                mag_is_db=not args.mag_linear,
            )

        if not per_file:
            print(f"Aviso: no se encontraron señales en {f}, se omite.", file=sys.stderr)
            continue

        multi = len(per_file) > 1
        for trace in per_file:
            col_label, *arrays = trace
            lbl = f"{file_label} – {col_label}" if multi else file_label
            all_traces.append((lbl, *arrays))

    if len(all_traces) < 2:
        p.error("Después de leer los archivos quedaron menos de dos señales para superponer.")

    if args.mode == "signal":
        plot_signal(all_traces, args.title, args.style, args.save)
    else:
        plot_bode(all_traces, args.title, args.style, args.save)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print(__doc__)
        sys.exit(0)
    main()