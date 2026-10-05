"""SimulationEngine — fasad run tunggal: dispatch -> KPI teknis -> finansial."""
from __future__ import annotations
import numpy as np

from .dispatch import simulate, SystemParams
from .kpi import technical_kpis, monthly_aggregates
from .finance import financial_kpis


class SimulationEngine:
    def __init__(self, load: np.ndarray, pv_norm: np.ndarray,
                 grid_status: np.ndarray, datetimes=None, deg_status=None):
        assert len(load) == len(pv_norm) == len(grid_status)
        self.load = np.asarray(load, float)
        self.pv_norm = np.asarray(pv_norm, float)
        self.grid_status = np.asarray(grid_status, float)
        self.datetimes = datetimes
        # DEG Status per-jam (opsional, import Excel) — None = tak diimpor,
        # diteruskan apa adanya ke simulate() (byte-identik bila None).
        self.deg_status = (np.asarray(deg_status, float)
                           if deg_status is not None else None)

    # akumulator berbasis ENERGI (kWh) — diskalakan tahunan (×annualize)
    _ENERGY_ACC = ('load', 'pv_gen', 'pv_inv_out', 'pv_excess', 'chg', 'chg_pv',
                   'chg_grid', 'chg_deg', 'dhg', 'grid_import', 'grid_export',
                   'grid_import_peak', 'grid_import_offpeak',
                   'deg_energy', 'served_pvbs', 'served_grid', 'unserved',
                   'deg1_energy', 'deg2_energy', 'deg3_energy',
                   'selfcons', 'selfcons_pv', 'selfcons_bess', 'selfcons_grid',
                   'selfcons_deg', 'selfcons_uns')
    # akumulator berbasis LANGKAH (jam operasi) — ×dt (langkah->jam) lalu ×annualize
    _STEP_ACC = ('deg_hours', 'outage_hours_total', 'deg_loading_sum')

    def run(self, params: SystemParams, cost_cfg: dict | None = None,
            record: bool = True, annualize: float = 1.0, progress=None):
        raw = simulate(self.load, self.pv_norm, self.grid_status,
                       params, record=record, progress=progress,
                       deg_status=self.deg_status)
        acc = raw['acc']
        # Ekstrapolasi jendela sub-tahun -> setahun agar KPI energi & finansial
        # tetap bermakna. Interval 1 jam/30 menit (setahun penuh) -> annualize=1
        # & dt=1 -> TIDAK ada perubahan (jalur tervalidasi utuh). Rasio (RF,
        # cycles, avg-loading, dsb.) invarian karena pembilang & penyebut sama-
        # sama terskala.
        dt = float(getattr(params, 'interval_h', 1.0) or 1.0)
        ann = float(annualize or 1.0)
        if ann != 1.0 or dt != 1.0:
            acc = dict(acc)
            for k in self._ENERGY_ACC:
                if k in acc:
                    acc[k] = np.asarray(acc[k], float) * ann
            for k in self._STEP_ACC:
                if k in acc:
                    acc[k] = np.asarray(acc[k], float) * dt * ann
        cc = cost_cfg or {}
        kpi = technical_kpis(acc, dict(
            bess_kwh=params.bess_kwh, soc_min=params.soc_min,
            soc_max=params.soc_max,
            deg_fuel_rate=cc.get('deg_fuel_rate'),
            deg_efficiency=params.deg_efficiency))
        kpi = {k: (float(v) if np.size(v) == 1 else v) for k, v in kpi.items()}
        fin = None
        if cost_cfg:
            fin = financial_kpis(kpi, dict(
                kwp=params.pv_kwp, kw_inv=params.pv_inv_kw,
                kwh_bess=params.bess_kwh, kw_deg=sum(params.deg_kw)),
                {**cost_cfg, 'pv_degradation': params.pv_degradation})
        series = raw.get('series')
        monthly = None
        if series is not None and self.datetimes is not None:
            monthly = monthly_aggregates(series, self.datetimes,
                                         fuel_rate=cc.get('deg_fuel_rate_eff'))
        return {'kpi': kpi, 'finance': fin, 'series': series,
                'monthly': monthly, 'params': params,
                'ma_window': raw.get('ma_window'),
                'ramp_up_step': raw.get('ramp_up_step'),
                'ramp_dn_step': raw.get('ramp_dn_step'),
                'pv_smooth_on': raw.get('pv_smooth_on')}
