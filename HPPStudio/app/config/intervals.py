"""Simulation interval & display-interval helpers.

Mendukung interval simulasi sub-jam dengan JENDELA (window) TERBATAS agar jumlah
langkah tetap wajar (lihat INTERVALS). Interval 1 jam / 30 menit menutup SATU
TAHUN penuh; interval lebih halus menutup jendela lebih pendek:

    interval     dt (jam)     jendela        langkah
    1 hour       1.0          1 tahun        8760
    30 minute    0.5          1 tahun        17.520
    1 minute     1/60         1 bulan (30 h) 43.200
    30 second    1/120        1 bulan (30 h) 86.400
    15 second    1/240        1 minggu       40.320
    1 second     1/3600       1 hari         86.400

Jendela SIMULASI (di atas) TERPISAH dari panjang DATA yang boleh diimpor:
data resolusi tinggi boleh mencakup setahun penuh (mis. 525.600 baris 1 menit);
simulasi mengambil JENDELA (window) dari titik mulai pilihan pengguna, lalu
energi diekstrapolasi ke setahun (annualization_factor) untuk KPI kWh/tahun.

Semua fungsi bersifat MURNI (tanpa GUI) sehingga mudah diuji. Interval "1 hour"
menghasilkan data IDENTIK dengan jalur lama (k=1, window=8760) -> paritas Excel
tetap terjaga.
"""
from __future__ import annotations
import numpy as np

HOURS_YEAR = 8760

# label -> (interval detik, jendela maksimum dalam JAM)
#   window_h menentukan berapa jam profil (dari awal) yang disimulasikan.
INTERVALS = {
    '1 hour':     (3600,   8760),        # 1 tahun
    '30 minute':  (1800,   8760),        # 1 tahun
    '1 minute':   (60,     30 * 24),     # 1 bulan (30 hari)
    '30 second':  (30,     30 * 24),     # 1 bulan (30 hari)
    '15 second':  (15,     7 * 24),      # 1 minggu
    '1 second':   (1,      1 * 24),      # 1 hari
}
INTERVAL_ORDER = ['1 hour', '30 minute', '1 minute', '30 second',
                  '15 second', '1 second']

# Preset DURASI simulasi (label -> jam). Dipilih pengguna di Dashboard; menentukan
# berapa jam profil (dari titik Mulai) yang BENAR-BENAR disimulasikan. Ditapis per
# interval oleh allowed_durations() agar jumlah langkah tetap wajar.
DURATION_PRESETS = [('1 hari', 24), ('1 minggu', 7 * 24), ('1 bulan', 30 * 24),
                    ('Setahun penuh', HOURS_YEAR)]

# pilihan interval TAMPILAN Dashboard (agregasi dari hasil simulasi)
DISPLAY_INTERVALS = {
    'Match simulation': 0,               # tampilkan apa adanya (sesuai simulasi)
    '1 second': 1, '15 second': 15, '30 second': 30,
    '1 minute': 60, '5 minute': 300, '15 minute': 900, '30 minute': 1800,
    '1 hour': 3600, '1 day': 86400,
}
DISPLAY_ORDER = ['Match simulation', '1 second', '15 second', '30 second',
                 '1 minute', '5 minute', '15 minute', '30 minute',
                 '1 hour', '1 day']


def interval_seconds(label: str) -> int:
    return int(INTERVALS.get(label, INTERVALS['1 hour'])[0])


def interval_dt_h(label: str) -> float:
    """Durasi satu langkah dalam JAM (dipakai engine: energi = daya x dt)."""
    return interval_seconds(label) / 3600.0


def interval_window_h(label: str) -> int:
    return int(INTERVALS.get(label, INTERVALS['1 hour'])[1])


def steps_per_hour(label: str) -> int:
    return int(round(3600 / interval_seconds(label)))


def window_steps(label: str) -> int:
    """Jumlah langkah simulasi untuk interval ini pada jendela maksimumnya."""
    return int(round(interval_window_h(label) * steps_per_hour(label)))


def is_full_year(label: str) -> bool:
    return interval_window_h(label) >= HOURS_YEAR


def annualization_factor(label: str) -> float:
    """Faktor ekstrapolasi energi jendela -> setahun (finansial). 1.0 bila
    jendela sudah setahun penuh (mis. 1 hour / 30 minute) -> jalur lama utuh."""
    wh = interval_window_h(label)
    return HOURS_YEAR / float(wh) if wh > 0 else 1.0


def annualization_factor_h(window_h) -> float:
    """Faktor ekstrapolasi energi -> setahun untuk jendela sebarang (JAM). Dipakai
    saat DURASI simulasi dipilih pengguna. window_h = jam yang benar-benar
    disimulasikan; 8760 -> 1.0 (jalur setahun penuh, paritas Excel tetap)."""
    wh = float(window_h)
    return HOURS_YEAR / wh if wh > 0 else 1.0


def allowed_durations(sim_label: str):
    """Preset DURASI simulasi yang layak untuk interval ini: hanya durasi yang
    tak melebihi jendela maksimum interval (interval lebih halus -> durasi lebih
    pendek). Untuk 6 interval baku, elemen terakhir selalu = window interval,
    sehingga default = perilaku lama (mis. 1 jam -> setahun, 1 menit -> 1 bulan)."""
    cap = interval_window_h(sim_label)
    return [(l, h) for (l, h) in DURATION_PRESETS if h <= cap] or \
        [(DURATION_PRESETS[0][0], cap)]


def _as_1d(a):
    return np.asarray(a, float).reshape(-1)


def resample_hourly(series_hourly, label: str, start_h: int = 0, window_h=None):
    """Bangun profil pada `label` dari profil PER JAM (8760/8784), piecewise-
    constant (daya tetap sepanjang jam -> energi identik). Ambil jendela
    [start_h, start_h+window_h) lalu tiap jam dipecah `k` langkah.

    window_h : durasi jendela (JAM); None -> jendela maksimum interval (jalur
    lama). Selalu dibatasi ke window maksimum interval & panjang data.
    label '1 hour' -> mengembalikan potongan jam apa adanya (k=1)."""
    x = _as_1d(series_hourly)
    n = x.size
    k = steps_per_hour(label)               # langkah per jam
    cap = interval_window_h(label)
    wh = cap if window_h is None else int(min(int(window_h), cap))
    win_h = min(wh, n)
    s = int(max(0, min(start_h, max(0, n - win_h))))
    seg = x[s:s + win_h]                     # potongan per jam (win_h nilai)
    if k == 1:
        return seg.copy()
    return np.repeat(seg, k)                 # tiap jam -> k langkah identik


def _interval_from_rows(n_rows: int):
    """Tebak interval dari JUMLAH BARIS saja (mandiri dari jendela simulasi):
    utamakan data yang mencakup SETAHUN penuh (n = jam/tahun × langkah/jam),
    lalu jendela sub-tahun yang dikenal, lalu 8760/8784 = per jam."""
    if not n_rows:
        return None
    for lab in INTERVAL_ORDER:                 # setahun penuh di interval ini
        sph = steps_per_hour(lab)
        if n_rows in (HOURS_YEAR * sph, 8784 * sph):
            return lab
    if n_rows in (8760, 8784):
        return '1 hour'
    for lab in INTERVAL_ORDER:                 # jendela sub-tahun yang dikenal
        if n_rows == window_steps(lab):
            return lab
    # umum: interval terhalus yang membuat n = (bilangan bulat jam) & ≤ 1 tahun
    for lab in reversed(INTERVAL_ORDER):
        sph = steps_per_hour(lab)
        if sph > 0 and n_rows % sph == 0 and 1 <= n_rows // sph <= 8784:
            return lab
    return None


def detect_interval_label(n_rows: int, datetimes=None):
    """Tebak label interval data. Utamakan selisih timestamp, TAPI abaikan bila
    durasi hasilnya absurd (mis. 525.600 baris × 1 jam = 60 tahun → timestamp
    tak tepercaya, mis. dari .hpps lama); lalu jatuh ke deteksi jumlah baris.
    Kembalikan label INTERVALS atau None."""
    sec = None
    if datetimes is not None:
        try:
            d = np.asarray(datetimes)
            if d.size >= 2:
                sec = float((np.datetime64(d[1]) - np.datetime64(d[0]))
                            / np.timedelta64(1, 's'))
        except Exception:
            sec = None
    lab_ts = None
    if sec is not None and sec > 0:
        best, bestd = None, 1e18
        for lab, (isec, _w) in INTERVALS.items():
            dd = abs(isec - sec)
            if dd < bestd:
                best, bestd = lab, dd
        if best is not None and bestd <= max(1.0, 0.25 * interval_seconds(best)):
            lab_ts = best
    # validasi: durasi (n × dt) harus wajar (≤ ~1 tahun); bila tidak, timestamp
    # tak tepercaya → pakai deteksi jumlah baris.
    if lab_ts is not None and n_rows:
        if n_rows * interval_dt_h(lab_ts) > 8784 * 1.05:
            lab_ts = None
    if lab_ts is not None:
        return lab_ts
    return _interval_from_rows(n_rows)


def aggregate_series(x, steps_group: int, how: str = 'mean'):
    """Agregasi deret `x` menjadi blok `steps_group` langkah.

    how='mean' untuk DAYA (kW) & SOC; how='sum' untuk energi per-langkah.
    Sisa langkah di ekor (tak genap satu blok) diagregasi apa adanya."""
    x = _as_1d(x)
    g = int(max(1, steps_group))
    n = x.size
    if g <= 1 or n == 0:
        return x.copy()
    nfull = n // g
    out = []
    if nfull:
        head = x[:nfull * g].reshape(nfull, g)
        out.append(head.sum(1) if how == 'sum' else head.mean(1))
    if n % g:
        tail = x[nfull * g:]
        out.append(np.array([tail.sum() if how == 'sum' else tail.mean()]))
    return np.concatenate(out) if out else x.copy()


def to_hourly(series, src_label: str):
    """Turunkan deret sumber ke basis PER JAM (rata-rata daya per jam). Sumber
    per-jam dikembalikan apa adanya."""
    x = _as_1d(series)
    k = steps_per_hour(src_label)
    if k <= 1:
        return x
    return aggregate_series(x, k, 'mean')


def build_sim_arrays(load, pv, grid, datetimes, sim_label, start_h: int = 0,
                     window_h=None, deg=None):
    """Bangun (load, pv, grid, dt_h, n, deg) siap-simulasi pada `sim_label`.

    window_h : DURASI simulasi (JAM) pilihan pengguna; None -> jendela maksimum
    interval (jalur lama). Selalu dibatasi ke window maksimum interval.
    deg      : (opsional) DEG Status per-jam (kode numerik, lihat
               app.data.importer) — diperlakukan SAMA spt grid (potongan apa
               adanya bila interval sumber=target; pembulatan piecewise-
               constant bila di-resample). None -> dikembalikan None (dispatch
               mengabaikannya sepenuhnya, byte-identik lama).

    * Sumber SAMA interval dgn target -> dipakai apa adanya (dijendela).
    * Sumber beda interval -> diturunkan ke basis per-jam lalu di-resample ke
      target (piecewise-constant, energi konsisten). Sumber per-jam (8760/8784)
      dgn target '1 hour' -> IDENTIK jalur lama.
    """
    load = _as_1d(load); pv = _as_1d(pv)
    grid = _as_1d(grid) if grid is not None else np.ones_like(load)
    has_deg = deg is not None
    deg = _as_1d(deg) if has_deg else None
    n = load.size
    src_label = detect_interval_label(n, datetimes) or '1 hour'
    dt_h = interval_dt_h(sim_label)
    cap = interval_window_h(sim_label)
    eff_win_h = cap if window_h is None else int(min(int(window_h), cap))
    if src_label == sim_label:
        sph = steps_per_hour(sim_label)
        ws = int(round(eff_win_h * sph))
        s = int(max(0, min(start_h * sph, max(0, n - ws))))
        sl = slice(s, s + min(ws, n))
        L, P, G = load[sl], pv[sl], grid[sl]
        D = deg[sl] if has_deg else None
    else:
        Lh = to_hourly(load, src_label)
        Ph = to_hourly(pv, src_label)
        Gh = to_hourly(grid, src_label)
        L = resample_hourly(Lh, sim_label, start_h, window_h=eff_win_h)
        P = resample_hourly(Ph, sim_label, start_h, window_h=eff_win_h)
        # status grid: pembulatan (0/1) setelah resample piecewise-constant
        G = np.round(resample_hourly(Gh, sim_label, start_h, window_h=eff_win_h))
        if has_deg:
            Dh = to_hourly(deg, src_label)
            D = np.round(resample_hourly(Dh, sim_label, start_h,
                                         window_h=eff_win_h))
        else:
            D = None
    m = int(min(L.size, P.size, G.size))
    return L[:m], P[:m], G[:m], dt_h, m, (D[:m] if has_deg else None)


def make_datetimes(sim_label: str, n: int, start='2025-01-01'):
    """DatetimeIndex sepanjang n pada interval `sim_label` (untuk agregasi &
    tampilan). Memerlukan pandas; pemanggil menangani ketiadaannya."""
    import pandas as pd
    sec = interval_seconds(sim_label)
    return pd.date_range(start, periods=int(n), freq=f'{sec}s')


# hari kumulatif SEBELUM tiap bulan (non-kabisat) — utk titik mulai simulasi
_CUM_DAYS = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]


def month_day_to_hour(month: int, day: int = 1) -> int:
    """Jam ke-berapa (dari awal tahun) untuk (bulan, hari). Basis non-kabisat;
    dipakai sebagai start_h jendela simulasi sub-tahun."""
    m = int(min(12, max(1, month)))
    d = int(max(1, day))
    return (_CUM_DAYS[m - 1] + (d - 1)) * 24


def resolve_sim_window(cfg: dict, n_rows: int, datetimes=None):
    """Titik mulai (start_h) & durasi (window_h) jendela simulasi — DIPAKAI
    BERSAMA oleh Dashboard, Optimization & Multi-Year agar SEMUA memakai
    jendela YANG SAMA (permintaan pengguna: tahun-1 Multi-Year == Dashboard,
    apa pun setelan Start/Durasi).

    Sumber setelan (persisten di cfg, ditulis oleh header Dashboard):
      * 'sim_start_month' (1-12), 'sim_start_day' (1-31) -> start_h.
      * 'sim_duration_h' (jam) -> durasi; <=0 / absen -> jendela PENUH interval
        (perilaku baku "Setahun penuh").
    Rumus IDENTIK dgn header Dashboard (_SimWorker/_run) sehingga konsisten.
    Tanpa setelan (proyek lama / default) -> (start_h=0, window_h=jendela penuh
    interval) = perilaku lama (paritas kanon/Excel terjaga).
    """
    lab = str(cfg.get('sim_interval', '1 hour'))
    full = interval_window_h(lab)
    dur_h = int(cfg.get('sim_duration_h', 0) or 0)
    month = int(cfg.get('sim_start_month', 1) or 1)
    day = int(cfg.get('sim_start_day', 1) or 1)
    # BAKU (tak ada setelan jendela): start=0 & jendela PENUH interval.
    # build_sim_arrays otomatis membatasi ke panjang data; jalur cepat
    # Multi-Year ('1 hour', jendela penuh) tetap byte-identik. Tak menyentuh
    # deteksi panjang-data sama sekali -> tak ada risiko salah-tebak interval
    # saat timestamp tak tersedia (mis. n baris ambigu spt 144).
    if dur_h <= 0 and month == 1 and day == 1:
        return 0, full
    # Ada setelan jendela (Start/Durasi non-baku): batasi ke durasi data.
    src = detect_interval_label(int(n_rows), datetimes) or '1 hour'
    src_h = int(n_rows) / max(steps_per_hour(src), 1)
    if dur_h <= 0:
        dur_h = full
    win_h = max(1, int(min(dur_h, full, int(src_h))))
    start_h = month_day_to_hour(month, day)
    start_h = int(max(0, min(start_h, max(0, int(src_h) - win_h))))
    return start_h, win_h


def window_start_datetime(datetimes, start_h: int = 0, default='2025-01-01'):
    """Timestamp mulai jendela = awal data + start_h jam. Fallback ke default."""
    try:
        import pandas as pd
        base = pd.Timestamp(np.asarray(datetimes).reshape(-1)[0])
        return base + pd.Timedelta(hours=float(start_h))
    except Exception:
        return default


def display_group_steps(sim_label: str, display_label: str) -> int:
    """Berapa langkah simulasi yang membentuk SATU titik tampilan Dashboard.
    'Match simulation' atau interval tampilan <= interval simulasi -> 1."""
    dsec = DISPLAY_INTERVALS.get(display_label, 0)
    ssec = interval_seconds(sim_label)
    if dsec <= 0 or dsec <= ssec:
        return 1
    return int(round(dsec / ssec))
