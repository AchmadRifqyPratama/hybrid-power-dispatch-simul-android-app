"""EMS BESS multi-mode berbasis PRIORITAS (mode Advanced).

Satu baterai melayani BEBERAPA mode sekaligus dalam SATU langkah, berbagi
anggaran SOC & PCS menurut urutan prioritas — BUKAN satu BESS terpisah per
mode. Fungsi `codispatch` bersifat MURNI & tervektorisasi (sumbu = kombinasi),
dipanggil per langkah oleh engine dispatch saat `bess_mode = Advanced`.

Prioritas default (tinggi → rendah; skala dropdown 1-5, BUKAN 1-7):
  1. Operating Reserve  — tahan SOC/PCS (membatasi discharge mode lain)
     ATAU Backup        — charge oportunistik dari surplus PV (siaga outage;
                           discharge SAAT outage ditangani pra-proses engine,
                           lihat dispatch.py blok "Backup", BUKAN di sini)
  2. Smoothing          — batasi ramp suplai DEG/Grid (EMA + batas naik/turun)
     ATAU Firming       — PV+BESS = daya konstan (base load)
  3. DG Minimum Loading — serap kelebihan DG (jaga DG ≥ min loading)
  4. Load Shifting      — geser energi (charge luar-puncak, discharge puncak)
  5. Peak Shaving       — discharge saat net load > ambang

Operating Reserve <-> Backup dan Smoothing <-> Firming SALING EKSKLUSIF (GUI,
lihat parameters_page.ParametersPage._mutual_exclusive) — mengaktifkan satu
mode dalam satu pasangan otomatis menonaktifkan pasangannya. Maks 5 mode
DISPATCH aktif bersamaan (satu dari tiap pasangan + DG Min Loading + Load
Shifting + Peak Shaving), karenanya dropdown Priority hanya 1-5.

Invariants (diuji di _t_multimode):
  * SOC tetap dalam [soc_min, soc_max]; |daya| ≤ PCS.
  * Cadangan (reserve) tak pernah dipakai dispatch normal.
  * Charge & discharge TIDAK terjadi bersamaan (dinetkan → satu arah/langkah).
  * Tidak ada energi ganda-hitung: discharge melayani beban (mengurangi
    grid/DEG), charge bersumber jelas (PV surplus / grid / DEG).
"""
from __future__ import annotations
import numpy as np


def codispatch(s: dict, md: dict, prev_pv, prev_ema,
               pre_dis=0.0, pre_chg=0.0, skip_sf=False):
    """Hitung aksi BESS satu langkah.

    s  : state per-langkah (array/skalar): qinv, pvd, ae, AD, dl, P, dgmin,
         Z, smin, smax, mchg, mdhg, srte, dt, hasb, goff, grid_room, hod.
    md : konfigurasi mode (flag bool + parameter, lihat dispatch._md).
    prev_pv  : output PV+BESS terkirim langkah sebelumnya (None pd langkah 1).
    prev_ema : nilai EMA PV langkah sebelumnya (None pd langkah 1).

    Kembalikan (out, prev_pv, prev_ema). out berisi:
      dis  : total discharge BESS (kW) → melayani beban (kurangi grid lalu DEG)
      cpv  : charge dari surplus PV (kW)
      cgr  : charge dari grid (kW)
      cdg  : charge dari kelebihan DEG (kW) (menaikkan output DEG = p_up)
      p_up : tambahan output DEG utk DG min loading (= cdg)
      pv_before : PV EnetAC di inverter SEBELUM shaping (= qinv, kW)
      pv_after  : PV EnetAC+BESS SETELAH shaping (= qinv bila idle). Telemetri
                  ramp DEG/Grid dihitung engine dari (beban − pv_before/after).
    """
    dt = s['dt']; srte = s['srte']; hasb = s['hasb']
    step_min = dt * 60.0                       # menit per langkah
    _z = np.zeros_like(np.asarray(s['Z'], float))

    # ---- anggaran (budget) SOC & PCS, dgn reserve ----
    resv_e = md['resv_frac'] * (s['smax'] - s['smin'])
    floor = s['smin'] + (resv_e if md['reserve'] else 0.0)
    D = np.where(hasb, np.maximum(0.0, (s['Z'] - floor) / dt * srte), 0.0)
    D = np.minimum(D, s['mdhg'])
    if md['reserve']:                          # tahan sebagian daya PCS
        D = np.maximum(0.0, D - md['resv_kw'])
    C = np.where(hasb, np.maximum(0.0, (s['smax'] - s['Z']) / dt / srte), 0.0)
    C = np.minimum(C, s['mchg'])
    # Kurangi anggaran yang SUDAH dipakai shaping PV (Smoothing/Firming) di
    # pra-proses engine, agar mode lain (kombinasi) hanya memakai sisa.
    D = np.maximum(0.0, D - np.asarray(pre_dis, float))
    C = np.maximum(0.0, C - np.asarray(pre_chg, float))
    # Satu arah per langkah: bila shaping sedang CHARGE (pre_chg>0), mode lain tak
    # boleh discharge; bila shaping DISCHARGE (pre_dis>0), mode lain tak boleh charge.
    # (BESS diprioritaskan untuk shaping PV; mencegah charge&discharge bersamaan.)
    D = np.where(np.asarray(pre_chg, float) > 1e-9, 0.0, D)
    C = np.where(np.asarray(pre_dis, float) > 1e-9, 0.0, C)

    qinv = np.asarray(s['qinv'], float)
    pv_surp = np.maximum(0.0, qinv - s['pvd'])   # surplus PV (kandidat curtail)
    AD = np.asarray(s['AD'], float)
    dl = np.asarray(s['dl'], float)
    # Target discharge: 0=Both (grid+DEG), 1=Grid saja, 2=DEG saja. Mode
    # peak-shave & load-shift menghitung discharge terhadap suplai target ini.
    _tgt = int(md.get('target', 0))
    netGD = AD if _tgt == 1 else (dl if _tgt == 2 else AD + dl)
    goff = s['goff']

    dis = _z.copy(); cpv = _z.copy(); cgr = _z.copy(); cdg = _z.copy()
    P = np.asarray(s['P'], float)
    prev_pv_out = qinv                       # state ramp DEG/Grid terkirim
    prev_ema_out = qinv                      # state EMA kebutuhan DEG/Grid
    pv_after = qinv.copy()                   # PV EnetAC+BESS SETELAH shaping

    def _pv_smooth():                       # Smoothing: output PV ikuti SETPOINT
        # SETPOINT output PV = MOVING AVERAGE PV EnetAC (window = input) yang KAUSAL:
        # dihitung dari PV EnetAC SEBELUM langkah ini (dipracompute+digeser di engine →
        # s['ma_pv']), lalu laju NAIK/TURUN-nya DIBATASI (pv_up/dn_kwmin) relatif
        # output langkah sebelumnya. Setpoint jadi PENGGANTI PV EnetAC; BESS mengisi
        # selisih thd PV EnetAC nyata (RTE & headroom PCS lewat anggaran D/C):
        #   setpoint > PV EnetAC → BESS discharge (isi kekurangan)
        #   setpoint < PV EnetAC → BESS charge  (serap kelebihan PV)
        # Output PV+BESS (= Plant Inj) MENGIKUTI setpoint ter-smoothed; DEG jadi
        # base load (melayani sisa beban = beban − output PV ter-smoothed).
        nonlocal dis, cpv, C, D, pv_surp
        nonlocal prev_pv_out, pv_after
        up = np.asarray(md['pv_up_kwmin'], float) * step_min   # batas naik/langkah
        dn = np.asarray(md['pv_dn_kwmin'], float) * step_min   # batas turun/langkah
        ma = np.asarray(s['ma_pv'], float)                     # MA PV EnetAC (window)
        base = qinv if prev_pv is None else np.asarray(prev_pv, float)
        hi = base + np.where(up > 0, up, np.inf)
        lo = base - np.where(dn > 0, dn, np.inf)
        sp = np.maximum(0.0, np.clip(ma, lo, hi))              # setpoint = MA + batas ramp
        fill = np.maximum(0.0, np.minimum(sp - qinv, D))       # setpoint>PV → discharge
        dis = dis + fill; D = D - fill
        absorb = np.maximum(0.0, np.minimum(np.minimum(qinv - sp, C), pv_surp))
        cpv = cpv + absorb; C = C - absorb; pv_surp = pv_surp - absorb  # setpoint<PV → charge
        delivered = np.maximum(0.0, qinv + fill - absorb)      # output PV+BESS = setpoint
        prev_pv_out = delivered
        pv_after = delivered

    def _firming():                        # PV+BESS = daya konstan (base load)
        # HANYA aktif saat PV membangkit (siang). Malam (PV=0) BESS TIDAK
        # discharge → PV+BESS = 0. Siang: PV<target → discharge; PV>target → charge.
        nonlocal dis, cpv, C, D, pv_surp, pv_after
        fp = np.asarray(md['firming_kw'], float)
        day = qinv > 1e-9                                      # PV ada (siang)
        fill = np.where(day, np.maximum(0.0, np.minimum(fp - qinv, D)), 0.0)
        dis = dis + fill; D = D - fill
        absorb = np.where(day, np.maximum(0.0, np.minimum(
            np.minimum(qinv - fp, C), pv_surp)), 0.0)
        cpv = cpv + absorb; C = C - absorb; pv_surp = pv_surp - absorb
        if not md.get('pv_smooth'):        # Smoothing (bila aktif) yg set pv_after
            pv_after = np.where(day, qinv + fill - absorb, 0.0)   # PV+BESS (kW)

    def _dg_minload():                      # serap kelebihan DG < min loading
        nonlocal cdg, C
        excess = np.maximum(0.0, np.asarray(s['dgmin'], float) - dl)
        a = np.maximum(0.0, np.minimum(excess, C))
        cdg = cdg + a; C = C - a

    def _load_shift():                      # puncak → discharge; luar → charge PV
        nonlocal dis, D, cpv, C, pv_surp
        hod = float(s['hod'])
        on_peak = (((hod >= md['arb_start']) and (hod < md['arb_end']))
                   if not md['arb_wrap'] else
                   ((hod >= md['arb_start']) or (hod < md['arb_end'])))
        if on_peak:
            d = np.maximum(0.0, np.minimum(np.maximum(0.0, netGD - dis), D))
            dis = dis + d; D = D - d
        else:
            a = np.maximum(0.0, np.minimum(pv_surp, C))
            cpv = cpv + a; C = C - a; pv_surp = pv_surp - a

    def _peak_shave():                      # discharge saat net load > ambang
        nonlocal dis, D
        excess = np.maximum(0.0, np.maximum(0.0, netGD - dis) - md['peak_kw'])
        d = np.maximum(0.0, np.minimum(excess, D))
        dis = dis + d; D = D - d

    def _backup():                          # siaga: charge oportunistik dr surplus PV
        # Di LUAR outage, Backup TAK PERNAH discharge lewat co-dispatch (spt
        # diminta: "BESS discharge hanya ketika DEG/Grid outage") — hanya
        # charge dari surplus PV bila ada anggaran (C), agar siap utk outage
        # berikutnya. Discharge SAAT outage ditangani pra-proses engine
        # (dispatch.py, lewat kanal shaping _Xsf/_Usf) — TIDAK di sini, demi
        # menghindari clip AD+deg_load=0 saat grid&DEG benar2 mati.
        nonlocal cpv, C, pv_surp
        a = np.maximum(0.0, np.minimum(pv_surp, C))
        cpv = cpv + a; C = C - a; pv_surp = pv_surp - a

    _fns = {'pv_smooth': _pv_smooth, 'firming': _firming,
            'dg_minload': _dg_minload, 'load_shift': _load_shift,
            'peak_shave': _peak_shave, 'backup': _backup}
    # proses mode aktif menurut urutan PRIORITAS (md['order']). Smoothing/Firming
    # ditangani pra-proses engine (skip_sf) → tak dijalankan lagi di sini.
    for _k in md.get('order', list(_fns)):
        if skip_sf and _k in ('pv_smooth', 'firming'):
            continue
        if md.get(_k):
            _fns[_k]()
    prev_pv = prev_pv_out; prev_ema = prev_ema_out

    # ---- netkan: satu arah per langkah (jaga PCS & fisika) ----
    tot_chg = cpv + cgr + cdg
    net = dis - tot_chg
    disch = np.maximum(0.0, net)                 # net discharge
    chg = np.maximum(0.0, -net)                  # net charge
    # skala sumber charge ke 'chg' (pertahankan proporsi sumber)
    scale = np.where(tot_chg > 1e-12, chg / np.maximum(tot_chg, 1e-12), 0.0)
    cpv = cpv * scale; cgr = cgr * scale; cdg = cdg * scale
    out = dict(dis=disch, cpv=cpv, cgr=cgr, cdg=cdg, p_up=cdg,
               pv_before=qinv, pv_after=pv_after)
    return out, prev_pv, prev_ema
