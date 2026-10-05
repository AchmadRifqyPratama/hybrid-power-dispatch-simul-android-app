"""Import data profil dari Excel/CSV dengan validasi 8760/8784 jam.

Format yang diterima (header fleksibel, case-insensitive):
  Load     : Datetime | Load (kW)
  PV ENetAC: Datetime | PV ENetAC (kW)
             (nama lama 'PV EArray' tetap dikenali)
  Grid     : Datetime | Grid Status (0/1)      [opsional]
  DEG      : Datetime | DEG Status (0/1/A)     [opsional]
             0 = DEG TAK TERSEDIA jam itu (spt outage/maintenance terjadwal),
             1 = DEG TERSEDIA (nyala/tidaknya TETAP keputusan dispatch normal
             — Load Supply Priority/DEG Interlock di halaman Parameters),
             A = Auto (setara 1 -- tak ada override; nilai bawaan bila kolom
             tak diisi/tak diimpor).
Satu file boleh memuat beberapa kolom sekaligus.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from ..config.i18n import tr

VALID_LENGTHS = (8760, 8784)

# Kode numerik internal utk kolom DEG Status (dipakai app.engine.dispatch):
#   0.0 = forced OFF (tak tersedia) | 1.0 = '1' eksplisit | 2.0 = 'A'/Auto.
# Engine hanya membedakan ==0.0 (mask) vs !=0.0 (tersedia spt biasa) — kode 1
# & 2 secara FUNGSIONAL identik, dipisah murni agar nilai asal pengguna bisa
# di-round-trip apa adanya saat diekspor ulang (lihat deg_status_to_label()).
DEG_STATUS_OFF = 0.0
DEG_STATUS_ON = 1.0
DEG_STATUS_AUTO = 2.0

_ALIASES = {
    'load': ['load', 'load (kw)', 'load_kw', 'beban', 'load needed',
             'load needed (kw)'],
    'pv': ['pv enetac', 'pv enetac (kw)', 'enetac',
           'pv earray', 'pv earray (kw)', 'earray', 'pv', 'pv_kw',
           'pv profile', 'pv base b (kw)'],
    'grid': ['grid status', 'pln status', 'grid', 'status', 'grid pln status'],
    'deg': ['deg status', 'genset status', 'diesel status', 'deg_status',
            'status deg', 'status genset'],
    'datetime': ['datetime', 'date time', 'timestamp', 'waktu', 'tanggal'],
}


class ImportError_(Exception):
    pass


def _find_col(cols, kind):
    low = {str(c).strip().lower(): c for c in cols}
    for alias in _ALIASES[kind]:
        if alias in low:
            return low[alias]
    for name_l, orig in low.items():
        if any(a in name_l for a in _ALIASES[kind]):
            return orig
    return None


def _parse_deg_status(series, col_name: str) -> np.ndarray:
    """Parse kolom DEG Status: sel boleh '0'/'1'/'A' (huruf, case-insensitive)
    ATAU numerik 0/1; sel kosong diperlakukan sbg 'A' (Auto). Kembalikan array
    kode numerik internal (lihat DEG_STATUS_OFF/ON/AUTO di atas)."""
    out = np.empty(len(series), float)
    for i, raw in enumerate(series):
        if raw is None or (isinstance(raw, float) and np.isnan(raw)):
            out[i] = DEG_STATUS_AUTO
            continue
        s = str(raw).strip()
        if s == '' or s.upper() == 'A':
            out[i] = DEG_STATUS_AUTO
        elif s in ('0', '0.0'):
            out[i] = DEG_STATUS_OFF
        elif s in ('1', '1.0'):
            out[i] = DEG_STATUS_ON
        else:
            raise ImportError_(
                tr('Kolom "{col}" baris {row}: nilai "{val}" tidak '
                   'dikenali — harus 0, 1, atau A (Auto).').format(
                    col=col_name, row=i + 2, val=raw))
    return out


def deg_status_to_label(code: float) -> str:
    """Kode numerik internal -> label kolom Excel ('0'/'1'/'A')."""
    if code == DEG_STATUS_OFF:
        return '0'
    if code == DEG_STATUS_ON:
        return '1'
    return 'A'


def read_profile_file(path: str) -> dict:
    """Baca file -> dict berisi 'datetimes' (DatetimeIndex) dan subset dari
    'load', 'pv', 'grid', 'deg' (np.ndarray float). Validasi panjang & NaN."""
    if path.lower().endswith(('.xlsx', '.xlsm', '.xls')):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)
    if df.empty:
        raise ImportError_(tr('File kosong.'))

    dt_col = _find_col(df.columns, 'datetime')
    if dt_col is None:
        dt_col = df.columns[0]
    dts = pd.to_datetime(df[dt_col], errors='coerce')
    if dts.isna().any():
        raise ImportError_(
            tr('Kolom datetime "{col}" mengandung nilai tidak valid.'
               ).format(col=dt_col))

    n = len(df)
    # Terima data PER JAM (8760/8784) ATAU data resolusi tinggi yang mencakup
    # rentang WAKTU wajar (≤ ~1 tahun). Panjang DATA TAK DIIKAT ke jendela
    # simulasi: interval dideteksi dari selisih timestamp, lalu diterima bila
    # jumlah baris = (bilangan bulat jam) × langkah-per-jam & durasi ≤ 1 tahun
    # (mis. 525.600 baris 1 menit = setahun; simulasi memakai jendela lebih
    # pendek dari data ini).
    _ok = n in VALID_LENGTHS
    if not _ok:
        try:
            from ..config.intervals import detect_interval_label, steps_per_hour
            _lab = detect_interval_label(n, dts)
            if _lab is not None:
                _sph = steps_per_hour(_lab)
                if _sph > 0 and n % _sph == 0 and 1 <= n // _sph <= 8784:
                    _ok = True
        except Exception:
            _ok = False
    if not _ok:
        raise ImportError_(
            tr('Jumlah baris {n} tidak dikenali — harus 8760/8784 (per jam) '
               'atau data resolusi tinggi dengan timestamp konsisten yang '
               'mencakup bilangan bulat jam hingga ≤ 1 tahun (mis. 525.600 = '
               '1 menit setahun, 43.200 = 1 menit sebulan).').format(n=n))

    out = {'datetimes': pd.DatetimeIndex(dts)}
    for kind in ('load', 'pv', 'grid'):
        col = _find_col(df.columns, kind)
        if col is None:
            continue
        v = pd.to_numeric(df[col], errors='coerce')
        if v.isna().any():
            bad = int(v.isna().sum())
            raise ImportError_(
                tr('Kolom "{col}": {bad} nilai non-numerik/kosong.'
                   ).format(col=col, bad=bad))
        arr = v.to_numpy(float)
        if kind in ('load', 'pv') and (arr < 0).any():
            raise ImportError_(
                tr('Kolom "{col}" mengandung nilai negatif.').format(col=col))
        if kind == 'grid' and not np.isin(np.unique(arr), (0.0, 1.0)).all():
            raise ImportError_(tr('Grid status hanya boleh 0 atau 1.'))
        out[kind] = arr
    # DEG Status: kolom TERPISAH (di samping Grid Status) — nilai campuran
    # 0/1/A (huruf), jadi diparse tersendiri (bukan pd.to_numeric langsung).
    deg_col = _find_col(df.columns, 'deg')
    if deg_col is not None:
        out['deg'] = _parse_deg_status(df[deg_col].tolist(), deg_col)
    if len(out) == 1:
        raise ImportError_(
            tr('Tidak ditemukan kolom Load / PV ENetAC / Grid Status / '
               'DEG Status.'))
    return out


def read_legacy_workbook(path: str) -> dict:
    """Import langsung dari workbook Excel lama (sizing_analysis_*.xlsx):
    ambil profil dari sheet Results (Load AJ + pola harian, PV AH, PLN L)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    if 'Results' not in wb.sheetnames:
        raise ImportError_(tr('Sheet "Results" tidak ditemukan — bukan '
                              'workbook sizing yang dikenal.'))
    ws = wb['Results']
    T = 8760
    dts, load, pv, grid = [], [], [], []
    for i in range(T):
        r = 13 + i
        dts.append(ws.cell(row=r, column=2).value)
        load.append(ws.cell(row=r, column=31).value)
        pv.append(ws.cell(row=r, column=34).value or 0.0)
        grid.append(ws.cell(row=r, column=12).value)
    # Sel hasil edit XML bisa tak punya cached value; Load berulang pola
    # harian (baris 37+ = baris-24), jadi isi dari 24 jam sebelumnya.
    for i, v in enumerate(load):
        if v is None:
            load[i] = load[i - 24] if i >= 24 else 0.0
    grid = [1.0 if g is None else g for g in grid]
    if sum(1 for v in load if not v) > 8000:
        raise ImportError_(tr('Nilai Load kosong — buka & simpan file di '
                              'Excel agar formula terhitung, lalu import '
                              'ulang.'))
    return {'datetimes': pd.DatetimeIndex(dts),
            'load': np.asarray(load, float),
            'pv': np.asarray(pv, float),
            'grid': np.asarray(grid, float)}


def default_grid_status(n: int) -> np.ndarray:
    return np.ones(n)


_SITE_ALIASES = {
    'site': ['site', 'name', 'nama', 'site name', 'nama site', 'lokasi',
             'location'],
    'lat': ['latitude', 'lat', 'lintang'],
    'lon': ['longitude', 'lon', 'lng', 'long', 'bujur'],
}


def read_site_coords(path: str) -> list:
    """Baca berkas Excel/CSV koordinat site (kolom: Site, Latitude, Longitude).

    Kembalikan list [(site_name:str, lat:float, lon:float), ...] terurut sesuai
    baris. Fleksibel terhadap variasi nama kolom (Site/Name/Nama,
    Latitude/Lat/Lintang, Longitude/Lon/Bujur)."""
    if path.lower().endswith(('.xlsx', '.xlsm', '.xls')):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)
    if df.empty:
        raise ImportError_(tr('Berkas koordinat kosong.'))
    low = {str(c).strip().lower(): c for c in df.columns}

    def find(kind):
        for a in _SITE_ALIASES[kind]:
            if a in low:
                return low[a]
        for name_l, orig in low.items():
            if any(a == name_l or a in name_l for a in _SITE_ALIASES[kind]):
                return orig
        return None

    c_site, c_lat, c_lon = find('site'), find('lat'), find('lon')
    if c_lat is None or c_lon is None:
        raise ImportError_(tr('Kolom Latitude/Longitude tidak ditemukan '
                              '(butuh kolom Site, Latitude, Longitude).'))
    out = []
    for i in range(len(df)):
        try:
            lat = float(df[c_lat].iloc[i]); lon = float(df[c_lon].iloc[i])
        except (TypeError, ValueError):
            continue
        if not (np.isfinite(lat) and np.isfinite(lon)):
            continue
        name = (str(df[c_site].iloc[i]).strip() if c_site is not None
                else f'Site {i + 1}')
        out.append((name, lat, lon))
    if not out:
        raise ImportError_(tr('Tidak ada baris koordinat valid.'))
    return out
