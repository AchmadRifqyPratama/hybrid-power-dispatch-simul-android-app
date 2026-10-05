"""Klien PVGIS (Photovoltaic Geographical Information System, EU JRC).

Mengunduh profil PV AC per-jam untuk koordinat tertentu lewat API terbuka
PVGIS (endpoint `seriescalc`, pvcalculation=1). Hasilnya berupa deret PV
ENetAC (kW) yang langsung dipakai sebagai profil PV aplikasi.

Dokumentasi: https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis_en

Modul MURNI-data (tanpa GUI, tanpa dependensi eksternal selain numpy). Semua
kegagalan jaringan/parsing dilempar sebagai PVGISError dengan pesan jelas.
"""
from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import numpy as np

from ..config.i18n import tr

_UA = 'HPPStudio/1.0 (Akartha Energi Baru)'
# Endpoint stabil PVGIS v5.2 (seriescalc = deret waktu per-jam).
_BASE = 'https://re.jrc.ec.europa.eu/api/v5_2/seriescalc'

# Tahun acuan (data radiasi PVGIS): non-kabisat -> 8760 jam, kabisat -> 8784.
DEFAULT_YEAR = 2019          # 8760 jam
LEAP_YEAR = 2020             # 8784 jam


class PVGISError(Exception):
    pass


def year_for_length(n_hours: int | None) -> int:
    """Pilih tahun acuan agar jumlah jam cocok dengan data lain (bila ada)."""
    return LEAP_YEAR if n_hours == 8784 else DEFAULT_YEAR


def combine_losses(components: dict, exclude=()) -> float:
    """Gabungkan komponen rugi (%) secara PERKALIAN: (1 - Π(1-rugiᵢ)) × 100.

    `exclude`: kunci komponen yang TIDAK ikut (mis. saat inverter & kabel DC
    dimodelkan eksplisit oleh koreksi tipe-PVSyst agar tidak dobel-hitung)."""
    eff = 1.0
    for k, v in (components or {}).items():
        if k in exclude:
            continue
        try:
            eff *= (1.0 - min(max(float(v), 0.0), 100.0) / 100.0)
        except (TypeError, ValueError):
            continue
    return (1.0 - eff) * 100.0


def apply_pvsyst_corrections(pv, poa, peak, dcac=1.2, inv_eff_pct=98.0,
                             dc_stc_pct=1.0, selfcons_frac=0.005):
    """Koreksi profil PVGIS agar lebih mendekati rantai loss PVSyst.

    Memperlakukan `pv` (P dari PVGIS, dengan inverter & kabel DC DIKELUARKAN
    dari loss datar PVGIS) sebagai daya DC ke inverter, lalu menerapkan efek
    yang BERGANTUNG IRADIANSI yang tidak dimodelkan PVGIS `seriescalc`:

      1) Rugi ohmik kabel DC ∝ iradiansi:  fraksi = dc_stc × (G/1000).
      2) Inverter (model linier):  P_ac = η·P_dc − P_selfcons  (rolloff beban
         rendah), lalu di-CLIP pada Pnom AC = peak / (DC/AC).

    Parameter
      pv, poa : np.ndarray — P (kW) & G(i) (W/m²) dari PVGIS (waktu lokal).
      peak    : kWp acuan profil (= Pnom DC array referensi).
      dcac    : rasio DC/AC (Pnom_DC / Pnom_AC). Clip di peak/dcac.
      inv_eff_pct : efisiensi plateau inverter (%) (mis. Euro/CEC).
      dc_stc_pct  : rugi kabel DC pada STC (%).
      selfcons_frac : konsumsi-sendiri inverter sebagai fraksi Pnom DC.

    Kembalikan np.ndarray P_ac (kW) terkoreksi."""
    pv = np.asarray(pv, float)
    poa = np.asarray(poa, float) if poa is not None else None
    peak = float(peak) if peak else 1.0
    # 1) kabel DC ∝ iradiansi
    if poa is not None and poa.shape == pv.shape:
        dc_frac = np.clip((float(dc_stc_pct) / 100.0) * (poa / 1000.0),
                          0.0, 0.9)
    else:
        dc_frac = float(dc_stc_pct) / 100.0          # fallback: datar
    p_dc = pv * (1.0 - dc_frac)
    # 2) inverter: efisiensi plateau + konsumsi-sendiri, lalu clipping
    eta = min(max(float(inv_eff_pct) / 100.0, 0.5), 1.0)
    p_self = max(float(selfcons_frac), 0.0) * peak
    p_ac = np.clip(eta * p_dc - p_self, 0.0, None)
    pnom_ac = peak / max(float(dcac), 1e-6)
    p_ac = np.minimum(p_ac, pnom_ac)
    return p_ac


def apply_bifacial_gain(pv, poa, ghi, albedo=0.20, bifaciality_pct=70.0,
                        rear_factor_pct=65.0, front_min=20.0, gain_cap=1.5):
    """Tambahkan gain BIFACIAL pada profil PV (model sederhana, per jam).

    PVGIS `seriescalc` hanya memodelkan sisi DEPAN (monofacial). Modul bifacial
    memperoleh tambahan dari iradiansi PANTULAN TANAH di sisi belakang:

      G_rear(t) = albedo × GHI(t) × rear_factor
      gain(t)   = 1 + bifaciality × G_rear(t) / G_front(t)
      PV_bi(t)  = PV(t) × gain(t)

    dengan G_front = G(i) (POA depan). `rear_factor` (0–1) menggabungkan view
    factor geometri + naungan struktur + non-uniformitas (fraksi cahaya pantul
    yang efektif sampai ke sisi belakang). Gain hanya dihitung saat G_front >
    `front_min` (hindari pembagian nol subuh/senja) dan dibatasi `gain_cap`.

    Butuh GHI (iradiansi global horizontal). Kembalikan PV (kW) terkoreksi;
    bila GHI None dikembalikan apa adanya."""
    pv = np.asarray(pv, float)
    if ghi is None or poa is None:
        return pv
    poa = np.asarray(poa, float)
    ghi = np.asarray(ghi, float)
    if poa.shape != pv.shape or ghi.shape != pv.shape:
        return pv
    phi = max(float(bifaciality_pct), 0.0) / 100.0
    rf = min(max(float(rear_factor_pct), 0.0) / 100.0, 1.0)
    alb = min(max(float(albedo), 0.0), 1.0)
    g_rear = alb * ghi * rf
    front = np.maximum(poa, 1e-6)
    ratio = np.where(poa > float(front_min), g_rear / front, 0.0)
    gain = np.clip(1.0 + phi * ratio, 1.0, float(gain_cap))
    return pv * gain


def weekday_shift(arr, from_year, to_year):
    """Geser deret per-jam agar hari-dalam-minggu selaras dengan tahun tujuan
    (mis. Senin→Senin). Reversibel. Sama dengan AppState._align_weekday."""
    import pandas as pd
    a = np.asarray(arr, float)
    try:
        fy, ty = int(from_year), int(to_year)
    except (TypeError, ValueError):
        return a
    if fy == ty or a.size == 0:
        return a
    try:
        wf = pd.Timestamp(f'{fy}-01-01').weekday()
        wt = pd.Timestamp(f'{ty}-01-01').weekday()
    except Exception:
        return a
    delta = (wt - wf) % 7
    if delta > 3:
        delta -= 7
    return np.roll(a, -delta * 24)


def _utc_offset_hours(lon: float) -> int:
    """Perkiraan selisih waktu lokal terhadap UTC dari bujur (≈15°/jam).

    Dipakai untuk menggeser deret PVGIS (UTC) ke waktu lokal. Untuk Indonesia
    cocok dengan zona resmi: WIB(+7, ~105°E), WITA(+8, ~120°E), WIT(+9, ~135°E).
    """
    try:
        return max(-12, min(14, int(round(float(lon) / 15.0))))
    except (TypeError, ValueError):
        return 0


def _fetch_horizontal_ghi(lat: float, lon: float, year: int | None = None,
                          timeout: float = 45.0):
    """Ambil GHI (iradiansi global HORIZONTAL, W/m²) per-jam dari PVGIS.

    Permintaan TERPISAH pada bidang DATAR (angle=0, aspect=0) sehingga nilai
    G(i) yang dikembalikan PVGIS setara GHI. Deret sudah digeser UTC->waktu
    lokal (via bujur) agar sejajar dengan profil PV. Kembalikan np.ndarray
    (W/m²), atau None bila data per-jam tak tersedia. Kegagalan jaringan/parse
    dilempar sebagai PVGISError (ditangani pemanggil)."""
    lat = float(lat); lon = float(lon)
    yr = int(year) if year else DEFAULT_YEAR
    params = {
        'lat': f'{lat:.6f}', 'lon': f'{lon:.6f}',
        'pvcalculation': 1, 'peakpower': '1', 'loss': '14',
        'pvtechchoice': 'crystSi', 'mountingplace': 'free',
        'angle': '0', 'aspect': '0',          # bidang datar -> G(i) = GHI
        'startyear': yr, 'endyear': yr,
        'outputformat': 'json', 'browser': 0,
    }
    url = _BASE + '?' + urlencode(params)
    req = Request(url, headers={'User-Agent': _UA})
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', 'replace')
    except (HTTPError, URLError, TimeoutError) as e:
        raise PVGISError(
            tr('Gagal mengunduh GHI dari PVGIS: {e}').format(e=e))
    try:
        doc = json.loads(raw)
    except Exception:
        raise PVGISError(tr('Respons GHI PVGIS bukan JSON yang valid.'))
    hourly = (doc.get('outputs') or {}).get('hourly')
    if not isinstance(hourly, list) or not hourly:
        return None

    def _g(row, key, default=0.0):
        try:
            v = row.get(key, default)
            return float(default if v is None else v)
        except (TypeError, ValueError):
            return default

    vals = [_g(r, 'G(i)', _g(r, 'Gi')) for r in hourly]
    arr = np.clip(np.nan_to_num(np.asarray(vals, float)), 0.0, None)
    offset = _utc_offset_hours(lon)
    if offset:
        arr = np.roll(arr, offset)
    return arr


def fetch_pv_profile(lat: float, lon: float, peakpower_kwp: float,
                     loss: float = 14.0, optimal: bool = True,
                     tilt: float = 0.0, azimuth: float = 0.0,
                     mounting: str = 'free',
                     year: int | None = None, with_ghi: bool = False,
                     pvsyst: dict | None = None, bifacial: dict | None = None,
                     timeout: float = 45.0) -> dict:
    """Unduh profil PV AC per-jam dari PVGIS untuk (lat, lon).

    Parameter
      peakpower_kwp : ukuran acuan array PV (kWp) untuk profil (skala linier).
      loss          : rugi sistem gabungan (%) — default 14% (bawaan PVGIS).
      optimal       : True -> PVGIS mengoptimalkan kemiringan & azimut.
      tilt, azimuth : dipakai hanya bila optimal=False (azimut PVGIS:
                      0=selatan, 90=barat, -90=timur, 180=utara).
      year          : tahun data radiasi; None -> DEFAULT_YEAR (8760 jam).
      with_ghi      : True -> unduh juga GHI (iradiansi global HORIZONTAL)
                      lewat permintaan kedua pada bidang datar (angle=0).

    Kembalikan dict:
      pv            : np.ndarray (kW) profil PV AC untuk `peakpower_kwp`.
      poa           : np.ndarray (W/m²) iradiansi global BIDANG ARRAY G(i).
      ghi           : np.ndarray (W/m²) iradiansi global HORIZONTAL (hanya
                      bila with_ghi=True & permintaan kedua berhasil; else None).
      n             : jumlah jam (8760/8784).
      annual_kwh    : energi PV tahunan (kWh) untuk `peakpower_kwp`.
      specific_yield: kWh/kWp/tahun.
      year, lat, lon, peakpower_kwp, loss, optimal, tilt, azimuth.
    """
    try:
        lat = float(lat); lon = float(lon)
        peak = max(float(peakpower_kwp), 0.001)
    except (TypeError, ValueError):
        raise PVGISError(tr('Koordinat/parameter PV tidak valid.'))
    yr = int(year) if year else DEFAULT_YEAR
    mount = mounting if mounting in ('free', 'building') else 'free'

    params = {
        'lat': f'{lat:.6f}', 'lon': f'{lon:.6f}',
        'pvcalculation': 1, 'peakpower': f'{peak:.6g}',
        'loss': f'{float(loss):.4g}', 'pvtechchoice': 'crystSi',
        'mountingplace': mount,
        'startyear': yr, 'endyear': yr,
        'outputformat': 'json', 'browser': 0,
    }
    if optimal:
        params['optimalangles'] = 1
    else:
        params['angle'] = f'{float(tilt):.3g}'
        params['aspect'] = f'{float(azimuth):.3g}'

    url = _BASE + '?' + urlencode(params)
    req = Request(url, headers={'User-Agent': _UA})
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', 'replace')
    except HTTPError as e:
        # PVGIS menaruh alasan galat pada body (mis. koordinat di laut / tahun
        # tak tersedia). Ambil agar pesan informatif.
        detail = ''
        try:
            detail = e.read().decode('utf-8', 'replace')
            j = json.loads(detail)
            detail = j.get('message', detail)
        except Exception:
            pass
        raise PVGISError(
            tr('PVGIS menolak permintaan (HTTP {code}). {detail}').format(
                code=e.code, detail=detail[:300]).strip())
    except (URLError, TimeoutError) as e:
        raise PVGISError(
            tr('Tidak dapat menghubungi server PVGIS — periksa koneksi '
               'internet. ({e})').format(e=e))
    except Exception as e:
        raise PVGISError(
            tr('Gagal mengunduh data PVGIS: {e}').format(e=e))

    try:
        doc = json.loads(raw)
    except Exception:
        raise PVGISError(tr('Respons PVGIS bukan JSON yang valid.'))
    hourly = (doc.get('outputs') or {}).get('hourly')
    if not isinstance(hourly, list) or not hourly:
        msg = ''
        if isinstance(doc.get('message'), str):
            msg = ' ' + doc['message']
        raise PVGISError(
            tr('Data per-jam PVGIS kosong/tidak ditemukan.') + msg)

    def _g(row, key, default=0.0):
        try:
            v = row.get(key, default)
            return float(default if v is None else v)
        except (TypeError, ValueError):
            return default

    p_w, poa, t2m, ws, times = [], [], [], [], []
    for row in hourly:
        p_w.append(_g(row, 'P'))
        poa.append(_g(row, 'G(i)', _g(row, 'Gi')))   # G(i) = bidang array (POA)
        t2m.append(_g(row, 'T2m'))
        ws.append(_g(row, 'WS10m'))
        times.append(str(row.get('time', '')))     # mis. '20190101:0010'
    pv_kw = np.asarray(p_w, float) / 1000.0        # W -> kW
    poa_arr = np.asarray(poa, float)
    t2m_arr = np.asarray(t2m, float)
    ws_arr = np.asarray(ws, float)
    n = int(pv_kw.shape[0])
    if n not in (8760, 8784):
        raise PVGISError(
            tr('PVGIS mengembalikan {n} jam (diharapkan 8760/8784).'
               ).format(n=n))
    if not np.isfinite(pv_kw).all() or (pv_kw < 0).any():
        pv_kw = np.clip(np.nan_to_num(pv_kw), 0.0, None)

    # PVGIS memberi data dalam WAKTU UTC. Data harus digeser ke WAKTU LOKAL
    # lokasi agar (a) pola harian benar (siang = puncak, malam = 0) dan
    # (b) SEJAJAR dengan profil beban yang memakai waktu lokal. Offset lokal
    # diperkirakan dari bujur (≈ 1 jam per 15°); untuk Indonesia ini tepat
    # (WIB=+7, WITA=+8, WIT=+9).
    import pandas as pd
    try:
        yr = int(pd.to_datetime(times[0], format='%Y%m%d:%H%M').year)
    except Exception:
        pass
    offset = _utc_offset_hours(lon)
    if offset:
        pv_kw = np.roll(pv_kw, offset)
        poa_arr = np.roll(poa_arr, offset)
        t2m_arr = np.roll(t2m_arr, offset)
        ws_arr = np.roll(ws_arr, offset)
    # Datetime = waktu LOKAL, mulai 1 Jan 00:00 pada tahun data PVGIS.
    datetimes = pd.date_range(f'{yr}-01-01', periods=n, freq='h')

    # GHI (iradiansi global HORIZONTAL) — permintaan kedua opsional pada bidang
    # datar (angle=0) sehingga G(i)=GHI. Gagal di sini TIDAK menggagalkan unduhan
    # PV; kolom GHI cukup dikosongkan.
    ghi_arr = None
    if with_ghi:
        try:
            g = _fetch_horizontal_ghi(lat, lon, yr, timeout)
            if g is not None and g.shape[0]:
                if g.shape[0] != n:
                    g = g[:n] if g.shape[0] > n else np.resize(g, n)
                ghi_arr = g
        except Exception:
            ghi_arr = None

    # Gain bifacial (opsional): tambahan dari iradiansi pantulan tanah pada sisi
    # belakang modul. Butuh GHI. Diterapkan pada DC SEBELUM koreksi inverter,
    # agar tambahan DC ikut terpengaruh clipping (bila koreksi PVSyst aktif).
    bifacial_meta = None
    if bifacial:
        albedo = float(bifacial.get('albedo', 0.20) or 0.0)
        bifac = float(bifacial.get('bifaciality', 70.0) or 0.0)
        rear = float(bifacial.get('rear_factor', 65.0) or 0.0)
        if ghi_arr is not None:
            before = float(pv_kw.sum())
            pv_kw = apply_bifacial_gain(pv_kw, poa_arr, ghi_arr, albedo,
                                        bifaciality_pct=bifac,
                                        rear_factor_pct=rear)
            after = float(pv_kw.sum())
            gain_pct = (after / before - 1.0) * 100.0 if before > 0 else 0.0
            bifacial_meta = {'albedo': albedo, 'bifaciality': bifac,
                             'rear_factor': rear, 'gain_pct': gain_pct}
        else:
            # Tanpa GHI, gain bifacial tak dapat dihitung -> lewati (tandai).
            bifacial_meta = {'albedo': albedo, 'bifaciality': bifac,
                             'rear_factor': rear, 'gain_pct': None}

    # Koreksi tipe-PVSyst (opsional): clipping inverter + kurva inverter +
    # kabel DC ∝ iradiansi. Diterapkan DI ATAS P PVGIS (inverter & kabel DC
    # harus SUDAH dikeluarkan dari `loss` datar oleh pemanggil).
    pvsyst_meta = None
    if pvsyst:
        dcac = float(pvsyst.get('dcac', 1.2) or 1.2)
        inv_eff = float(pvsyst.get('inv_eff', 98.0) or 98.0)
        dc_stc = float(pvsyst.get('dc_stc', 1.0) or 0.0)
        pv_kw = apply_pvsyst_corrections(pv_kw, poa_arr, peak, dcac=dcac,
                                         inv_eff_pct=inv_eff, dc_stc_pct=dc_stc)
        pvsyst_meta = {'dcac': dcac, 'inv_eff': inv_eff, 'dc_stc': dc_stc,
                       'pnom_ac': peak / max(dcac, 1e-6)}

    annual = float(pv_kw.sum())                     # kWh (dt = 1 jam)
    return {
        'pv': pv_kw, 'poa': poa_arr, 'ghi': ghi_arr,
        't2m': t2m_arr, 'ws10m': ws_arr,
        'datetimes': datetimes, 'n': n, 'utc_offset': offset,
        'annual_kwh': annual,
        'specific_yield': annual / peak,
        'year': yr, 'lat': lat, 'lon': lon,
        'peakpower_kwp': peak, 'loss': float(loss), 'mounting': mount,
        'optimal': bool(optimal), 'tilt': float(tilt), 'azimuth': float(azimuth),
        'pvsyst': pvsyst_meta, 'bifacial': bifacial_meta,
    }


def batch_pvgis_pv(loaded: list, coords: list, cfg: dict, progress=None):
    """Untuk batch multi-site 'koordinat per-site': unduh PV PVGIS tiap site.

    loaded  : [{'site','load','grid','datetimes',...}] hasil baca berkas data.
    coords  : [(site_name, lat, lon), ...] dari berkas koordinat.
    cfg     : konfigurasi aktif — memakai cfg['pvgis_opts'] (tilt/azimut/
              mounting/loss/year dari jendela Home) dan pv_base_annual
              (Parameters) sebagai peakpower acuan.

    Tiap site: PV diganti hasil PVGIS pada koordinatnya; Load & Grid
    diselaraskan (weekday) ke tahun data PVGIS. Cocokkan koordinat via NAMA
    site (jatuh ke urutan baris bila nama tak cocok).

    Kembalikan (updated_loaded, errors:list[(site, msg)])."""
    opts = dict(cfg.get('pvgis_opts') or {})
    optimal = bool(opts.get('optimal', True))
    tilt = float(opts.get('tilt', 0.0) or 0.0)
    azimuth = float(opts.get('azimuth', 0.0) or 0.0)
    loss = float(opts.get('loss', 14.0) if opts.get('loss') is not None
                 else 14.0)
    mounting = opts.get('mounting', 'free') or 'free'
    year_opt = opts.get('year')
    peak = float(cfg.get('pv_base_annual', 1103.76) or 0.0) or 1103.76
    # Koreksi tipe-PVSyst (opsional) — konsisten dengan unduhan halaman Home:
    # keluarkan inverter & kabel DC dari loss datar, lalu modelkan eksplisit.
    pvsyst = None
    if opts.get('pvsyst_match'):
        comps = opts.get('loss_components') or {}
        if comps:
            loss = combine_losses(comps, exclude=('inverter', 'cabling_dc'))
        pvsyst = {
            'dcac': float(opts.get('dcac', 1.2) or 1.2),
            'inv_eff': float(opts.get('inv_eff', 98.0) or 98.0),
            'dc_stc': float((comps.get('cabling_dc', 1.0) if comps else 1.0)
                            or 0.0),
        }
    # Modul bifacial (opsional) — butuh GHI, jadi paksa unduh GHI bila aktif.
    bifacial = None
    if opts.get('bifacial'):
        bifacial = {
            'albedo': float(opts.get('albedo', 0.20) or 0.0),
            'bifaciality': float(opts.get('bifaciality', 70.0) or 0.0),
            'rear_factor': float(opts.get('rear_factor', 65.0) or 0.0),
        }

    cmap = {str(nm).strip().lower(): (la, lo) for nm, la, lo in coords}
    updated, errors = [], []
    for i, item in enumerate(loaded):
        site = item.get('site', f'Site {i + 1}')
        if progress:
            progress(i, len(loaded), site)
        co = cmap.get(str(site).strip().lower())
        if co is None and i < len(coords):
            co = (coords[i][1], coords[i][2])       # jatuh ke urutan baris
        if co is None:
            errors.append((site, tr('koordinat tidak ditemukan')))
            updated.append(item)
            continue
        lat, lon = co
        load = item.get('load')
        grid = item.get('grid')
        deg = item.get('deg')
        n = int(len(load)) if load is not None else 8760
        yr = int(year_opt) if year_opt else year_for_length(n)
        try:
            r = fetch_pv_profile(lat, lon, peak, loss=loss, optimal=optimal,
                                 tilt=tilt, azimuth=azimuth, mounting=mounting,
                                 year=yr, with_ghi=bool(bifacial),
                                 pvsyst=pvsyst, bifacial=bifacial)
        except Exception as e:
            errors.append((site, str(e)))
            updated.append(item)
            continue
        pv = np.asarray(r['pv'], float)
        if load is not None and len(load) != len(pv):
            m = len(load)
            pv = pv[:m] if len(pv) > m else np.resize(pv, m)
        try:
            from_year = int(item['datetimes'][0].year)
        except Exception:
            from_year = int(cfg.get('simulation_year', r['year']) or r['year'])
        to_year = int(r['year'])
        it = dict(item)
        it['load'] = (weekday_shift(load, from_year, to_year)
                      if load is not None else load)
        it['grid'] = (weekday_shift(grid, from_year, to_year)
                      if grid is not None else grid)
        # DEG Status (kode 0/1/2, lihat app.data.importer) -- digeser sama
        # persis dgn Load/Grid (roll murni, tak ada interpolasi/rata-rata)
        # agar kode round-trip apa adanya walau kalender bergeser.
        it['deg'] = (weekday_shift(deg, from_year, to_year)
                     if deg is not None else deg)
        it['pv'] = pv
        it['lat'] = lat; it['lon'] = lon; it['pvgis_year'] = to_year
        # Profil PV mewakili array `peak` kWp; konsumen HARUS memakai
        # pv_base_annual = peak agar penskalaan engine (pv_kwp/pv_base) benar.
        it['pv_base_annual'] = peak
        updated.append(it)
    return updated, errors


def export_pvgis_xlsx(path: str, res: dict, datetimes=None) -> str:
    """Tulis data PVGIS per-jam ke berkas Excel (.xlsx).

    Sheet 'PVGIS Hourly' : Datetime, PV Power (kW), G(i) bidang array (W/m²),
                           GHI horizontal (W/m², bila tersedia), suhu T2m (°C),
                           kecepatan angin (m/s).
    Sheet 'Info'         : metadata lokasi/orientasi/energi.
    Mengembalikan path berkas.
    """
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill
    from openpyxl.utils import get_column_letter
    from ..config.i18n import tr

    pv = np.asarray(res['pv'], float)
    n = int(pv.shape[0])
    # POA = iradiansi bidang array G(i); GHI = iradiansi global HORIZONTAL.
    poa_src = res.get('poa')
    ghi_src = res.get('ghi')
    if poa_src is None:                 # kompat lama: 'ghi' dulu menyimpan G(i)
        poa_src, ghi_src = ghi_src, None
    poa = np.asarray(poa_src if poa_src is not None else np.zeros(n), float)
    ghi = np.asarray(ghi_src, float) if ghi_src is not None else None
    has_ghi = (ghi is not None and ghi.shape[0] == n
               and float(np.nanmax(np.abs(ghi))) > 0)
    t2m = np.asarray(res.get('t2m', np.zeros(n)), float)
    wind = np.asarray(res.get('ws10m', np.zeros(n)), float)
    has_t = t2m.shape[0] == n and float(np.nanmax(np.abs(t2m))) > 0
    has_w = wind.shape[0] == n and float(np.nanmax(np.abs(wind))) > 0

    if datetimes is None or len(datetimes) != n:
        datetimes = res.get('datetimes')       # timestamp asli PVGIS
    if datetimes is None or len(datetimes) != n:
        import pandas as pd
        datetimes = pd.date_range(f"{int(res.get('year', 2019))}-01-01",
                                  periods=n, freq='h')
    try:
        pydts = [d.to_pydatetime() for d in datetimes]
    except AttributeError:
        pydts = list(datetimes)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'PVGIS Hourly'
    headers = [tr('Datetime'), tr('PV Power (kW)'),
               tr('In-plane Irradiance G(i) (W/m2)')]
    if has_ghi:
        headers.append(tr('Global Horizontal Irradiance GHI (W/m2)'))
    if has_t:
        headers.append(tr('Ambient Temperature (C)'))
    if has_w:
        headers.append(tr('Wind Speed 10m (m/s)'))
    ws.append(headers)
    hfill = PatternFill('solid', fgColor='16A34A')
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = hfill
        cell.alignment = Alignment(horizontal='center', vertical='center')
    for i in range(n):
        row = [pydts[i], round(float(pv[i]), 4), round(float(poa[i]), 2)]
        if has_ghi:
            row.append(round(float(ghi[i]), 2))
        if has_t:
            row.append(round(float(t2m[i]), 2))
        if has_w:
            row.append(round(float(wind[i]), 2))
        ws.append(row)
    for i in range(2, n + 2):
        ws.cell(row=i, column=1).number_format = 'yyyy-mm-dd hh:mm'
    ws.freeze_panes = 'A2'
    widths = ([20, 14, 30] + ([34] if has_ghi else [])
              + ([22] if has_t else []) + ([20] if has_w else []))
    for idx, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = w

    info = wb.create_sheet('Info')
    orient = (tr('Optimal tilt/azimuth') if res.get('optimal')
              else f"{tr('Tilt')} {res.get('tilt', 0):.0f}° / "
                   f"{tr('Azimuth')} {res.get('azimuth', 0):.0f}°")
    mount_lbl = (tr('Building-integrated') if res.get('mounting') == 'building'
                 else tr('Free-standing'))
    rows = [
        (tr('Source'), 'PVGIS — re.jrc.ec.europa.eu (seriescalc)'),
        (tr('Latitude'), f"{res.get('lat', 0):.6f}"),
        (tr('Longitude'), f"{res.get('lon', 0):.6f}"),
        (tr('Time zone (approx.)'), f"UTC{int(res.get('utc_offset', 0)):+d} "
         + tr('(local time)')),
        (tr('Data Year'), str(res.get('year', ''))),
        (tr('Reference PV Size (kWp)'), f"{res.get('peakpower_kwp', 0):,.2f}"),
        (tr('Orientation'), orient),
        (tr('Mounting'), mount_lbl),
        (tr('System Loss (%)'), f"{res.get('loss', 0):.1f}"),
        (tr('Annual PV Energy (kWh)'), f"{res.get('annual_kwh', 0):,.0f}"),
        (tr('Specific Yield (kWh/kWp/yr)'),
         f"{res.get('specific_yield', 0):,.0f}"),
    ]
    if has_ghi:
        rows.append((tr('Annual GHI (kWh/m2/yr)'),
                     f"{float(ghi.sum()) / 1000.0:,.0f}"))
    ps = res.get('pvsyst')
    if ps:
        rows.append((tr('PVSyst-like correction'), tr('Applied')))
        rows.append((tr('Inverter DC/AC ratio'), f"{ps.get('dcac', 0):.2f}"))
        rows.append((tr('Inverter Pnom AC (kW)'), f"{ps.get('pnom_ac', 0):,.1f}"))
        rows.append((tr('Inverter efficiency (%)'),
                     f"{ps.get('inv_eff', 0):.2f}"))
        rows.append((tr('DC cabling @STC (%)'), f"{ps.get('dc_stc', 0):.2f}"))
    bf = res.get('bifacial')
    if bf:
        rows.append((tr('Bifacial module'), tr('Applied')))
        rows.append((tr('Albedo'), f"{bf.get('albedo', 0):.2f}"))
        rows.append((tr('Bifaciality (%)'), f"{bf.get('bifaciality', 0):.2f}"))
        rows.append((tr('Rear-side factor (%)'),
                     f"{bf.get('rear_factor', 0):.2f}"))
        gp = bf.get('gain_pct')
        rows.append((tr('Bifacial gain (%)'),
                     (f"{gp:.2f}" if gp is not None else tr('n/a (no GHI)'))))
    rows.append((tr('Hours'), str(n)))
    for k, v in rows:
        info.append([k, v])
    for i in range(1, len(rows) + 1):
        info.cell(row=i, column=1).font = Font(bold=True)
    info.column_dimensions['A'].width = 30
    info.column_dimensions['B'].width = 44

    wb.save(path)
    return path
