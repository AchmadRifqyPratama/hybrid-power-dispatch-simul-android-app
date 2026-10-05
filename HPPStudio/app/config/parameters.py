"""Skema parameter — SATU-SATUNYA tempat mendefinisikan parameter aplikasi.

Menambah parameter baru = menambah satu entri Param di SCHEMA; halaman
Parameters otomatis membuat widget (textbox/dropdown/checkbox), tooltip,
satuan, dan validasi min/maks dari definisi ini.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import os


@dataclass
class Param:
    key: str
    # dtype 'heading' = judul sub-bagian (label full-width, tanpa input);
    # tak masuk cfg/defaults, hanya penata tampilan halaman Parameters.
    label: str
    dtype: str = 'float'            # float | int | bool | choice | text | heading
    default: object = 0.0
    unit: str = ''
    tooltip: str = ''
    minimum: float | None = None
    maximum: float | None = None
    choices: list = field(default_factory=list)
    decimals: int = 3


def _hdr(key: str, label: str) -> 'Param':
    """Buat baris JUDUL sub-bagian untuk halaman Parameters."""
    return Param(key, label, 'heading', '')


# Peta mode BESS (checkbox) -> kunci prioritasnya. Dipakai ParamGroupBox agar
# dropdown prioritas tampil SEBARIS dengan checkbox mode (bukan baris sendiri).
MODE_PRIORITY = {
    'm_pv_smooth':  'prio_pv_smooth',
    'm_firming':    'prio_firming',
    'm_load_shift': 'prio_load_shift',
    'm_peak_shave': 'prio_peak_shave',
    'm_dg_minload': 'prio_dg_minload',
    'm_reserve':    'prio_reserve',
    'm_backup':     'prio_backup',
}


# Laju konsumsi bahan bakar DEG bawaan (L/kWh). 0,303 L/kWh setara dengan
# efisiensi generator 33% pada model lama: fuel = energi / (0,33 × 10 kWh/L)
# = energi × 0,303. Fuel = laju × energi DEG (kWh) — konversi langsung.
DEFAULT_FUEL_RATE = round(1.0 / (0.33 * 10.0), 3)     # 0.303


SCHEMA: dict[str, list[Param]] = {
    'General': [
        Param('project_name', 'Project Name', 'text', 'Hybrid Plant Project',
              tooltip='Nama proyek untuk laporan'),
        Param('customer', 'Customer', 'text', '', tooltip='Nama pelanggan'),
        Param('site_name', 'Site Name', 'text', '',
              tooltip='Nama site / lokasi pembangkit (dipakai pada nama '
                      'file ekspor dan lembar Info)'),
        Param('location', 'Location', 'text', '', tooltip='Lokasi site'),
        Param('latitude', 'Latitude', 'float', 0.0, '°',
              'Lintang lokasi proyek (−90…90). Pilih lewat tombol '
              '"Pilih di Peta" pada halaman Home.', -90.0, 90.0, decimals=6),
        Param('longitude', 'Longitude', 'float', 0.0, '°',
              'Bujur lokasi proyek (−180…180). Pilih lewat tombol '
              '"Pilih di Peta" pada halaman Home.', -180.0, 180.0, decimals=6),
        Param('simulation_year', 'Simulation Year', 'int', 2025, '',
              'Tahun kalender profil data', 2000, 2100),
        Param('sim_interval', 'Simulation Interval', 'choice', '1 hour',
              tooltip='Resolusi waktu simulasi (khusus halaman Dashboard). '
                      'Interval lebih halus memakai JENDELA lebih pendek agar '
                      'ringan: 1 hour & 30 minute = 1 tahun penuh; 1 minute & '
                      '30 second = 1 bulan; 15 second = 1 minggu; 1 second = '
                      '1 hari. Titik MULAI jendela dipilih di Dashboard. Energi '
                      'diekstrapolasi ke setahun (kWh/tahun). Data per-jam '
                      'otomatis di-resample; boleh juga import data resolusi '
                      'tinggi. Optimization & Multi-Year tetap basis 1 jam.',
              choices=['1 hour', '30 minute', '1 minute', '30 second',
                       '15 second', '1 second']),
    ],
    'Grid': [
        Param('grid_enabled', 'Any Grid Connection', 'bool', True,
              tooltip='Nonaktifkan untuk sistem off-grid'),
        Param('grid_kw', 'Grid Capacity', 'float', 23.0, 'kW',
              'Kapasitas sambungan PLN', 0.0, 1e6),
        Param('grid_min_loading', 'Grid Minimum Loading', 'float', 0.01, '%',
              'Loading minimum grid saat tersambung', 0.0, 1.0),
        Param('grid_max_loading', 'Grid Maximum Loading', 'float', 1.0, '%',
              'Loading maksimum grid', 0.0, 1.5),
        Param('allow_export', 'PV-BESS Export to Grid', 'bool', False,
              tooltip='Izinkan ekspor kelebihan PV ke grid (ekstensi; '
                      'default OFF)'),
        Param('grid_tariff_per_kwh', 'Grid Tariff', 'float', 1500.0, 'Rp/kWh',
              'Tarif energi impor grid', 0.0, 1e6),
        Param('export_tariff_per_kwh', 'Export Tariff', 'float', 1000.0,
              'Rp/kWh', 'Harga jual energi ekspor ke grid (dipakai bila '
              'PV-BESS Export to Grid aktif)', 0.0, 1e6),
    ],
    'Dispatch Strategy': [
        Param('bess_mode', 'Dispatch Mode', 'choice', 'Standard',
              tooltip='Standard: dispatch seperti biasa (prioritas beban). '
                      'Advanced: pilih FUNGSI BESS khusus (Peak Shaving, dll.) '
                      'di atas dispatch dasar.',
              choices=['Standard', 'Advanced']),
        # ==== EMS BESS multi-mode (mode Advanced) — beberapa boleh aktif ====
        # serentak; satu baterai melayani semua menurut PRIORITAS (nomor di
        # sebelah tiap mode; 1 = tertinggi). Lihat engine/bess_modes.py.
        # Judul sub-bagian (tampil hanya saat Advanced) — memisahkan fungsi
        # peran BESS lanjutan dari aturan dispatch dasar di bawahnya.
        _hdr('__hdr_bess_role', 'BESS Role Function'),
        Param('adv_target', 'Discharge Target', 'choice', 'Both',
              tooltip='Suplai yang DIKURANGI saat BESS discharge (mode '
                      'Advanced): Grid saja, DEG saja, atau keduanya. '
                      'Memengaruhi Peak Shaving & Load Shifting dan penerapan '
                      'discharge ke suplai.',
              choices=['Both', 'Grid', 'DEG']),
        Param('m_pv_smooth', 'Smoothing', 'bool', False,
              tooltip='Haluskan output PV yang dikirim ke sistem. Setpoint output '
                      'PV = Moving Average (MA) PV EnetAC, lalu laju NAIK/TURUN-nya '
                      'dibatasi PV Ramp-Up/Down Limit. BESS mengisi kekurangan '
                      '(setpoint > PV EnetAC → discharge) & menyerap kelebihan '
                      '(setpoint < PV EnetAC → charge) agar output PV mengikuti '
                      'kurva halus; DEG menjadi base load. Tak dapat aktif '
                      'bersamaan dengan Firming — mengaktifkan salah satu '
                      'otomatis menonaktifkan yang lain.'),
        Param('prio_pv_smooth', 'Priority', 'choice', '2',
              tooltip='Nomor PRIORITAS mode ini dalam co-dispatch (1 = tertinggi). Saat beberapa mode aktif, mode prioritas lebih tinggi mendapat anggaran SOC/PCS lebih dulu.', choices=['1', '2', '3', '4', '5']),
        Param('pv_ramp_up_kwmin', 'PV Ramp-Up Limit', 'float', 0.0,
              'kW/min', 'Batas laju NAIK (kW/menit) output PV ter-smoothed '
              '(setpoint). 0 = tanpa batas naik (hanya MA).', 0.0, 1e7),
        Param('pv_ramp_dn_kwmin', 'PV Ramp-Down Limit', 'float', 0.0,
              'kW/min', 'Batas laju TURUN (kW/menit) output PV ter-smoothed '
              '(setpoint). 0 = tanpa batas turun (hanya MA).', 0.0, 1e7),
        Param('smoothing_window', 'MA Window', 'int', 10, 'langkah',
              'Ukuran jendela Moving Average (jumlah nilai PV EnetAC sebelumnya). '
              'Setpoint = rata-rata bergerak PV sepanjang window ini, lalu '
              'dibatasi PV Ramp-Up/Down Limit. Besar = lebih halus/lag besar.',
              1, 100000),
        Param('m_firming', 'Firming', 'bool', False,
              tooltip='PV+BESS men-deliver DAYA KONSTAN (target) sebagai base load '
                      'dalam JENDELA firming: BESS discharge saat PV di bawah target '
                      '& charge dari kelebihan PV saat di atas target. Di LUAR '
                      'jendela, PV dipakai untuk charge BESS saja (tak diinjeksi). '
                      'Tak dapat aktif bersamaan dengan Smoothing — mengaktifkan '
                      'salah satu otomatis menonaktifkan yang lain.'),
        Param('prio_firming', 'Priority', 'choice', '2',
              tooltip='Nomor PRIORITAS mode ini dalam co-dispatch (1 = tertinggi). Saat beberapa mode aktif, mode prioritas lebih tinggi mendapat anggaran SOC/PCS lebih dulu.', choices=['1', '2', '3', '4', '5']),
        Param('firming_kw', 'Target Power', 'float', 0.0, 'kW',
              'Daya konstan (kW) yang di-deliver PV+BESS sebagai base load. BESS '
              'menutup kekurangan (PV < target) & menyerap kelebihan (PV > '
              'target).', 0.0, 1e7),
        Param('firming_trigger', 'Firming Window', 'choice', 'PV Power',
              tooltip='Penentu KAPAN Firming aktif: "PV Power" (ambang daya PV '
                      'EnetAC) atau "Time" (jam mulai/berhenti). Di luar jendela, '
                      'PV hanya untuk charge BESS.', choices=['PV Power', 'Time']),
        Param('firming_pv_start', 'PV Threshold Start', 'float', 0.0, 'kW',
              'Pagi: Firming MULAI saat PV EnetAC melampaui nilai ini. Sebelum itu '
              'PV hanya untuk charge BESS. (mode Firming Window = PV Power)', 0.0, 1e7),
        Param('firming_pv_end', 'PV Threshold End', 'float', 0.0, 'kW',
              'Sore: Firming BERHENTI saat PV EnetAC turun di bawah nilai ini. '
              'Setelahnya PV hanya untuk charge BESS. (mode PV Power)', 0.0, 1e7),
        Param('firming_time_start', 'Start Time', 'float', 0.0, 'h',
              'Jam (0–24) Firming MULAI. Sebelumnya PV hanya untuk charge BESS. '
              '(mode Firming Window = Time)', 0.0, 24.0),
        Param('firming_time_end', 'End Time', 'float', 0.0, 'h',
              'Jam (0–24) Firming BERHENTI. Setelahnya PV hanya untuk charge BESS. '
              '(mode Time)', 0.0, 24.0),
        Param('m_load_shift', 'Load Shifting', 'bool', False,
              tooltip='Simpan energi saat surplus/luar-puncak, lepaskan saat '
                      'puncak untuk mengurangi grid/DEG. Memperhitungkan '
                      'efisiensi charge/discharge (RTE).'),
        Param('prio_load_shift', 'Priority', 'choice', '4',
              tooltip='Nomor PRIORITAS mode ini dalam co-dispatch (1 = tertinggi). Saat beberapa mode aktif, mode prioritas lebih tinggi mendapat anggaran SOC/PCS lebih dulu.', choices=['1', '2', '3', '4', '5']),
        Param('arb_peak_start', 'Peak Window Start', 'int', 18,
              'h', 'Jam MULAI jendela puncak (0-23): di dalamnya BESS discharge; '
                   'di luar BESS diisi. Start > End → melewati tengah malam.',
              0, 23),
        Param('arb_peak_end', 'Peak Window End', 'int', 22,
              'h', 'Jam AKHIR jendela puncak (0-23, eksklusif).', 0, 23),
        Param('tariff_offpeak_per_kwh', 'Off-Peak Tariff',
              'float', 1000.0, 'Rp/kWh', 'Tarif grid luar puncak (finansial). '
              'Impor jam puncak memakai Grid Tariff biasa.', 0.0, 1e6),
        Param('m_peak_shave', 'Peak Shaving', 'bool', False,
              tooltip='Batasi daya puncak dari grid/DEG. BESS discharge saat '
                      'net load melebihi ambang. discharge = max(0, net load − '
                      'ambang).'),
        Param('prio_peak_shave', 'Priority', 'choice', '5',
              tooltip='Nomor PRIORITAS mode ini dalam co-dispatch (1 = tertinggi). Saat beberapa mode aktif, mode prioritas lebih tinggi mendapat anggaran SOC/PCS lebih dulu.', choices=['1', '2', '3', '4', '5']),
        Param('peak_shave_kw', 'Threshold', 'float', 0.0, 'kW',
              'Ambang net load. Di atas ambang, BESS discharge menutup '
              'selisihnya (sebatas SOC & PCS).', 0.0, 1e7),
        Param('m_dg_minload', 'DG Minimum Loading', 'bool', False,
              tooltip='Cegah DG beroperasi di bawah minimum loading: kelebihan '
                      'output DG (di atas beban) dialihkan mengisi BESS. Pakai '
                      'Minimum Loading (grup Diesel).'),
        Param('prio_dg_minload', 'Priority', 'choice', '3',
              tooltip='Nomor PRIORITAS mode ini dalam co-dispatch (1 = tertinggi). Saat beberapa mode aktif, mode prioritas lebih tinggi mendapat anggaran SOC/PCS lebih dulu.', choices=['1', '2', '3', '4', '5']),
        Param('m_reserve', 'Operating Reserve', 'bool', False,
              tooltip='Tahan sebagian kapasitas BESS (SOC & daya PCS) agar '
                      'SELALU tersedia untuk kejadian tak terduga (DG trip, PV '
                      'anjlok, lonjakan beban). Dispatch normal tak boleh '
                      'memakai cadangan ini. Tak dapat aktif bersamaan dengan '
                      'Backup — mengaktifkan salah satu otomatis menonaktifkan '
                      'yang lain.'),
        Param('prio_reserve', 'Priority', 'choice', '1',
              tooltip='Nomor PRIORITAS mode ini dalam co-dispatch (1 = tertinggi). Saat beberapa mode aktif, mode prioritas lebih tinggi mendapat anggaran SOC/PCS lebih dulu.', choices=['1', '2', '3', '4', '5']),
        Param('reserve_frac', 'SOC Fraction', 'float', 0.0,
              '%', 'Persentase energi guna BESS (SOC maks−min) yang DITAHAN '
              'sebagai cadangan (0–100%). Dispatch normal tak menyentuhnya.',
              0.0, 100.0),
        Param('reserve_kw', 'Power', 'float', 0.0, 'kW',
              'Daya PCS yang DITAHAN sebagai cadangan (tak dipakai dispatch '
              'normal).', 0.0, 1e7),
        Param('m_backup', 'Backup', 'bool', False,
              tooltip='BESS (+PV bila tersedia) mengambil alih PENUH pelayanan '
                      'beban saat Grid DAN DEG sama-sama tak tersedia (outage) '
                      '— mengesampingkan Smoothing/Firming kapan pun outage '
                      'terjadi. Di luar outage: BESS hanya charge oportunistik '
                      'dari surplus PV (siaga), tak pernah discharge. Tak dapat '
                      'aktif bersamaan dengan Operating Reserve — mengaktifkan '
                      'salah satu otomatis menonaktifkan yang lain.'),
        Param('prio_backup', 'Priority', 'choice', '1',
              tooltip='Nomor PRIORITAS mode ini dalam co-dispatch (1 = tertinggi). Saat beberapa mode aktif, mode prioritas lebih tinggi mendapat anggaran SOC/PCS lebih dulu.', choices=['1', '2', '3', '4', '5']),
        # Judul sub-bagian (SELALU tampil, di mode Standard MAUPUN Advanced) —
        # parameter dasar dispatch & sumber daya yang berlaku utk KEDUA mode
        # (bukan eksklusif salah satu). Lihat VISIBILITY: TIDAK boleh dibungkus
        # aturan _adv_bess (dulu pernah disembunyikan saat Advanced -- sudah
        # dibetulkan, lihat catatan di definisi VISIBILITY di bawah).
        _hdr('__hdr_base_dispatch', 'Base Parameters'),
        Param('load_priority', 'Load Supply Priority', 'choice',
              'PV -> Grid -> BESS -> DEG',
              tooltip='Urutan sumber yang melayani beban. Mode Grid dahulu '
                      'memaksimalkan impor grid sebelum PV/BESS. '
                      'Bila DEG Interlock with Grid dinonaktifkan, '
                      'genset naik satu tingkat sebelum BESS: '
                      'PV → Grid → DEG → BESS, dan '
                      'Grid → DEG → PV → BESS.',
              choices=['PV -> Grid -> BESS -> DEG',
                       'Grid -> PV -> BESS -> DEG',
                       'PV -> BESS -> Grid -> DEG']),
        Param('load_priority_split', 'Load Priority Follows Grid Status',
              'bool', False,
              tooltip='Aktif: pilih skenario load priority terpisah untuk saat '
                      'grid tersedia (status 1) dan saat grid padam '
                      '(status 0). Engine memakai skenario status-1 pada jam '
                      'grid menyala dan skenario status-0 pada jam grid padam. '
                      'Nonaktif: satu skenario Load Supply Priority berlaku '
                      'untuk semua jam.'),
        Param('load_priority_on', 'Load Priority — Grid Available (1)',
              'choice', 'Grid -> PV -> BESS -> DEG',
              tooltip='Skenario prioritas beban saat GRID TERSEDIA '
                      '(grid status = 1). Dipakai bila '
                      '"Load Priority Follows Grid Status" aktif.',
              choices=['PV -> Grid -> BESS -> DEG',
                       'Grid -> PV -> BESS -> DEG',
                       'PV -> BESS -> Grid -> DEG']),
        Param('load_priority_off', 'Load Priority — Grid Unavailable (0)',
              'choice', 'PV -> BESS -> DEG',
              tooltip='Skenario prioritas beban saat GRID PADAM '
                      '(grid status = 0). Grid memasok 0 kW sehingga posisi '
                      '"Grid" dalam rantai tak berpengaruh — opsi diringkas ke '
                      'strategi yang benar-benar berbeda (urutan PV/BESS/DEG). '
                      'Saat DEG Interlock with Grid nonaktif, genset dapat naik '
                      'sebelum BESS (PV → DEG → BESS / DEG → PV → BESS). '
                      'Dipakai bila "Load Priority Follows Grid Status" aktif.',
              choices=['PV -> BESS -> DEG',
                       'PV -> DEG -> BESS',
                       'DEG -> PV -> BESS']),
        Param('grid_charge_enabled', 'Allow Grid Charging to BESS', 'bool',
              True, tooltip='Nonaktifkan agar BESS hanya di-charge dari PV; '
                    'grid tidak pernah mengisi baterai (W = 0).'),
        Param('deg_charge_enabled', 'Allow DEG Charging to BESS', 'bool',
              False, tooltip='Genset menambah output '
                    'Saat genset menyala dengan pembebanan di bawah Minimum Loading, '
                    'kekurangannya dialihkan untuk mengisi BESS sehingga '
                    'genset beroperasi minimal pada minimum loading-nya. '
                    'Hanya berlaku bila DEG Interlock nonaktif (saat '
                    'interlock, bus DEG terpisah dari PV-BESS).'),
        Param('deg_grid_interlock', 'DEG Interlock with Grid', 'bool',
              True, tooltip='Aktif: bus grid dan bus genset saling kunci '
                    '(seperti transfer switch) — keduanya tidak pernah '
                    'memasok beban bersamaan. Bila grid (+PV/BESS) tidak '
                    'sanggup memikul beban, sistem beralih ke genset dan '
                    'grid dilepas. Nonaktif: genset boleh beroperasi '
                    'paralel dengan grid, hanya menutup kekurangan yang '
                    'tidak sanggup dipikul grid.'),
        Param('grid_interlock', 'Grid Interlock with PV-BESS', 'bool',
              False, tooltip='Aktif: beban dilayani Grid ATAU PV-BESS '
                    'secara eksklusif (bus terpisah). PV-BESS dipakai '
                    'bila sanggup memikul seluruh beban jam itu; selain '
                    'itu grid yang memikul dan PV hanya mengisi BESS. '
                    'Nonaktif: grid dan PV-BESS boleh memasok beban '
                    'bersamaan (perilaku standar).'),
        Param('deg_interlock', 'DEG Interlock with PV-BESS', 'bool',
              True, tooltip='Aktif: sumber beban eksklusif — Grid+PV-BESS '
                    'ATAU DEG; saat DEG memikul beban, PV hanya charge ke '
                    'BESS, BESS tidak discharge, dan grid hanya boleh '
                    'charge (bila diizinkan). Nonaktif: DEG hanya menutup '
                    'residu dan boleh paralel dengan PV/BESS/Grid.'),
        Param('deg_sync', 'DEG Can Synchronise', 'bool', True,
              tooltip='Aktif (default): genset boleh paralel & berbagi beban — '
                      'dispatch seperti sekarang. Nonaktif: genset TIDAK dapat '
                      'sinkron — hanya SATU genset menyala pada satu waktu; '
                      'yang terkecil kapasitasnya menyala lebih dulu, dan saat '
                      'mencapai maximum loading ia mati lalu genset lebih besar '
                      'yang menyala, dan seterusnya.'),
        Param('deg_always', 'DEG Must Always Run', 'bool', False,
              tooltip='Aktif: saat GRID PADAM atau proyek TANPA GRID, minimal '
                      'SATU genset (terkecil) WAJIB menyala & melayani beban '
                      'lebih dulu. Bila beban < MINIMUM LOADING: jika "Allow DEG '
                      'Charging to BESS" AKTIF, DEG naik ke minimum loading & '
                      'kelebihannya mengisi BESS (selama SOC < SOC maksimum & PCS '
                      'cukup); jika NONAKTIF, DEG hanya sebesar beban (di bawah '
                      'minimum loading) tanpa mengisi BESS. Saat grid TERSEDIA '
                      'fitur ini tak berpengaruh — DEG bekerja normal. Nonaktif '
                      '(default): DEG hanya menyala saat dibutuhkan.'),
        Param('deg_grid_former', 'Grid-Forming DEG Priority', 'choice', 'Auto',
              choices=['Auto', 'DEG-1', 'DEG-2', 'DEG-3'],
              tooltip='Genset mana yang WAJIB menyala lebih dulu sebagai '
                      'grid-forming saat "DEG Must Always Run" aktif & grid '
                      'padam. "Auto" memilih — tiap jam — genset yang MINIMUM '
                      'LOADING-nya (kapasitas × Lmin) paling dekat ke beban; '
                      'jadi saat beban rendah dipakai genset lebih KECIL agar '
                      'paling mendekati minimum loadingnya (surplus terkecil). '
                      'DEG-1/2/3 = genset tetap. Bila memilih unit 0 kW / tak '
                      'aktif, otomatis kembali ke Auto.'),
        Param('deg_options_split', 'DEG Options Follow Grid Status', 'bool',
              False,
              tooltip='Aktif: atur "DEG Interlock with PV-BESS" dan "Allow DEG '
                      'Charging to BESS" terpisah untuk saat grid tersedia '
                      '(status 1) dan grid padam (status 0). Engine memakai '
                      'setelan status-1 pada jam grid menyala dan setelan '
                      'status-0 pada jam grid padam. Nonaktif: satu setelan '
                      'berlaku untuk semua jam.'),
        Param('deg_interlock_on',
              'DEG Interlock with PV-BESS — Grid Available (1)', 'bool', True,
              tooltip='DEG Interlock with PV-BESS saat GRID TERSEDIA '
                      '(status 1). Dipakai bila "DEG Options Follow Grid '
                      'Status" aktif.'),
        Param('deg_interlock_off',
              'DEG Interlock with PV-BESS — Grid Unavailable (0)', 'bool', True,
              tooltip='DEG Interlock with PV-BESS saat GRID PADAM (status 0). '
                      'Dipakai bila "DEG Options Follow Grid Status" aktif.'),
        Param('deg_charge_on',
              'Allow DEG Charging to BESS — Grid Available (1)', 'bool', False,
              tooltip='Allow DEG Charging to BESS saat GRID TERSEDIA '
                      '(status 1). Otomatis nonaktif bila interlock status-1 '
                      'aktif (bus DEG terpisah).'),
        Param('deg_charge_off',
              'Allow DEG Charging to BESS — Grid Unavailable (0)', 'bool', False,
              tooltip='Allow DEG Charging to BESS saat GRID PADAM (status 0). '
                      'Otomatis nonaktif bila interlock status-0 aktif (bus '
                      'DEG terpisah).'),
        Param('strict_charge_priority', 'Strict Charging Priority', 'bool',
              False, tooltip='Aktif: sumber prioritas kedua MENUNGGU — pada '
                    'PV -> Grid, grid tidak mengisi BESS selama PV masih '
                    'mengisi; pada Grid -> PV sebaliknya. Nonaktif: keduanya '
                    'boleh mengisi bersamaan, berbagi limit PCS & headroom '
                    'SOC menurut urutan prioritas.'),
        Param('charge_priority', 'BESS Charging Priority', 'choice',
              'PV -> Grid',
              tooltip='Sumber energi yang diprioritaskan untuk mengisi BESS '
                      'ketika keduanya tersedia (charge dari grid tetap hanya '
                      'saat SOC di bawah ambang).',
              choices=['PV -> Grid', 'Grid -> PV']),
    ],
    'Diesel': [
        Param('deg_count', 'Total DEG', 'choice', '1',
              tooltip='Jumlah genset aktif', choices=['0', '1', '2', '3']),
        Param('diesel_price_per_l', 'Diesel Price', 'float', 21000.0, 'Rp/L',
              'Harga solar per liter', 0.0, 1e6),
        Param('deg1_kw', 'DEG-1 Capacity', 'float', 30.0, 'kW', '', 0.0, 1e6),
        Param('deg2_kw', 'DEG-2 Capacity', 'float', 0.0, 'kW', '', 0.0, 1e6),
        Param('deg3_kw', 'DEG-3 Capacity', 'float', 0.0, 'kW', '', 0.0, 1e6),
        Param('deg_min_loading', 'Minimum Loading per DEG', 'float', 0.0, '%',
              'Pembebanan minimum tiap genset. Bila Allow DEG Charging to BESS '
              'aktif, genset menambah output untuk mengisi BESS agar '
              'beroperasi minimal pada loading ini', 0.0, 1.0),
        Param('deg_max_loading', 'Maximum Loading per DEG', 'float', 1.0, '%',
              'Batas loading maksimum, asumsi sama untuk semua DEG — dipakai '
              'sebagai ambang eskalasi alokasi genset (AE* ≤ ΣD·Lmax)',
              0.0, 1.2),
        Param('deg1_fuel_rate', 'DEG-1 Fuel Consumption Rate', 'float',
              DEFAULT_FUEL_RATE, 'L/kWh',
              'Laju konsumsi bahan bakar DEG-1 — konversi langsung energi '
              'genset ke liter solar: Fuel (L) = laju × energi DEG (kWh). '
              'Nilai 0,303 setara efisiensi 33% (referensi sebelumnya).',
              0.0, 2.0),
        Param('deg2_fuel_rate', 'DEG-2 Fuel Consumption Rate', 'float',
              DEFAULT_FUEL_RATE, 'L/kWh',
              'Laju konsumsi bahan bakar DEG-2 — Fuel (L) = laju × energi '
              'DEG-2 (kWh). Boleh berbeda dari DEG lain.', 0.0, 2.0),
        Param('deg3_fuel_rate', 'DEG-3 Fuel Consumption Rate', 'float',
              DEFAULT_FUEL_RATE, 'L/kWh',
              'Laju konsumsi bahan bakar DEG-3 — Fuel (L) = laju × energi '
              'DEG-3 (kWh). Boleh berbeda dari DEG lain.', 0.0, 2.0),
        Param('deg_cost_per_kw', 'DEG CAPEX', 'float', 3000000.0, 'Rp/kW',
              'Biaya investasi genset', 0.0, 1e9),
    ],
    'Battery': [
        Param('bess_kwh', 'Nominal Capacity', 'float', 215.0, 'kWh',
              'Kapasitas nominal BESS', 0.0, 1e7),
        Param('soc_init', 'Initial SOC', 'float', 0.5, '%', '', 0.0, 1.0),
        Param('soc_min', 'Minimum SOC', 'float', 0.1, '%', '', 0.0, 1.0),
        Param('soc_max', 'Maximum SOC', 'float', 0.95, '%', '', 0.0, 1.0),
        Param('rte', 'Round Trip Efficiency', 'float', 0.913, '%', '', 0.3, 1.0),
        Param('max_charge_kw', 'Maximum Charge Power', 'float', 108.0, 'kW',
              'Batas daya charge PCS', 0.0, 1e6),
        Param('max_discharge_kw', 'Maximum Discharge Power', 'float', 108.0, 'kW',
              'Batas daya discharge PCS', 0.0, 1e6),
        Param('charge_from_grid_below_soc', 'Charge from Grid below SOC',
              'float', 0.6, '%', 'BESS di-charge dari grid bila SOC < nilai ini',
              0.0, 1.0),
        Param('bess_self_cons_kw', 'Self Consumption', 'float', 0.0, 'kWh/h',
              'Konsumsi sendiri BESS (HVAC, BMS, PCS idle, dll.) dalam kWh per '
              'jam, berlaku sepanjang waktu selama BESS terpasang. Merupakan '
              'beban TAMBAHAN: pembangkitan harus memasok beban + self '
              'consumption. Isi 0 untuk menonaktifkan.', 0.0, 1e6),
        Param('bess_sc_source', 'Self Consumption Supplied by', 'choice',
              'PV+BESS', tooltip=
              'Sumber utama pemasok self consumption BESS. PV+BESS: dipasok PV '
              'lalu discharge BESS lebih dulu; kekurangannya dipasok Grid lalu '
              'DEG. DEG/Grid: dipasok Grid (bila tersedia) lalu DEG lebih dulu; '
              'kekurangannya dipasok kelebihan PV lalu BESS.',
              choices=['PV+BESS', 'DEG/Grid']),
        Param('bess_cost_per_kwh', 'BESS CAPEX', 'float', 6000000.0, 'Rp/kWh',
              'Biaya investasi baterai', 0.0, 1e9),
    ],
    'PV': [
        Param('pv_kwp', 'PV Capacity (DC)', 'float', 37.5, 'kWp',
              'Kapasitas array PV terpasang', 0.0, 1e7),
        Param('pv_module_wp', 'PV Module Rating', 'float', 625.0, 'Wp',
              'Rating modul PV', 100.0, 1000.0),
        Param('pv_inv_kw', 'PV Inverter Capacity (AC)', 'float', 30.0, 'kW',
              '', 0.0, 1e7),
        Param('pv_base_annual', 'Base Profile Plant Size', 'float', 1103.76,
              'kWp', 'Kapasitas pembangkit acuan yang menghasilkan profil PV '
              'ENetAC yang diimpor (dari PVsyst). Output = ENetAC × kWp '
              'desain ÷ nilai ini. Isi 1 bila profil sudah per-kWp.',
              1e-6, 1e9),
        Param('pv_cost_per_kwp', 'PV CAPEX', 'float', 9000000.0, 'Rp/kWp',
              'Biaya investasi PV per kWp', 0.0, 1e9),
        Param('inverter_cost_per_kw', 'Inverter CAPEX', 'float', 1500000.0,
              'Rp/kW', 'Biaya inverter per kW', 0.0, 1e9),
    ],
    'Finance': [
        Param('om_fraction', 'O&M Cost', 'float', 0.015, '%CAPEX/yr',
              'Biaya operasi & pemeliharaan tahunan', 0.0, 0.2),
        Param('accessories_cost', 'Accessories Cost', 'float', 0.0, 'Rp',
              'Biaya aksesoris — komponen CAPEX tetap, ditambahkan langsung '
              'ke total CAPEX', 0.0, 1e15),
        Param('logistic_cost', 'Logistic Cost', 'float', 0.0, 'Rp',
              'Biaya logistik — komponen CAPEX tetap, ditambahkan langsung '
              'ke total CAPEX', 0.0, 1e15),
        Param('epc_cost_per_kwp', 'EPC Cost', 'float', 0.0, 'Rp/kWp',
              'Biaya EPC per kWp PV — CAPEX EPC = nilai ini × kapasitas '
              'PV (kWp)', 0.0, 1e9),
        Param('baseline_mode', 'Baseline Comparison', 'choice', 'diesel_only',
              tooltip='Pembanding penghematan: diesel murni atau grid+diesel',
              choices=['diesel_only', 'grid_diesel']),
        Param('finance_scope', 'Financial Analysis', 'choice', 'PV-BESS-DEG',
              tooltip='Batasi LCOE, CAPEX & OPEX (halaman Results & '
              'Optimization Constraints) hanya ke komponen biaya & energi '
              'teknologi terpilih. "DEG" = Diesel genset + Grid (gabungan, '
              'selaras label "DEG/Grid" pada grafik EMS); "PV-BESS" = PV + '
              'Inverter + BESS saja; "PV-BESS-DEG" (baku) = seluruh sistem, '
              'tak berubah dari sebelumnya. Biaya CAPEX tetap (Accessories & '
              'Logistic) selalu diikutkan penuh apa pun pilihannya. NPV, '
              'IRR, ROI, dan Payback TETAP dihitung dari seluruh sistem '
              'terlepas dari pilihan ini.',
              choices=['DEG', 'PV-BESS', 'PV-BESS-DEG']),
    ],
    'Multi-Year (Lifetime)': [
        Param('project_lifetime_y', 'Project Lifetime', 'int', 20, 'yr',
              'Umur proyek untuk analisis finansial', 1, 40),
        Param('discount_rate', 'Discount Rate', 'float', 0.08, '%/yr',
              'Tingkat diskonto untuk NPV & LCOE', 0.0, 0.5),
        Param('inflation', 'Inflation', 'float', 0.03, '%/yr',
              'Eskalasi harga energi tahunan', 0.0, 0.5),
        Param('pv_degradation', 'PV Degradation per Year', 'float', 0.005,
              '%/yr', 'Degradasi tahunan (analisis finansial)', 0.0, 0.05),
        Param('bess_lifetime_y', 'BESS Lifetime', 'int', 10, 'yr',
              'Umur pakai BESS. Setelah mencapai umur ini, BESS diganti baru '
              '(biaya = CAPEX BESS) dan SOH kembali 100%. Isi 0 untuk '
              'menonaktifkan penggantian berbasis umur.', 0, 50),
        Param('bess_soh_threshold', 'BESS SOH Threshold', 'float', 0.7, '%',
              'Ambang State of Health. Bila SOH turun di bawah nilai ini, '
              'BESS diganti baru (biaya = CAPEX BESS) dan SOH kembali 100%. '
              'Isi 0 untuk menonaktifkan penggantian berbasis SOH.', 0.0, 1.0),
        Param('bess_soh_source', 'BESS SOH Model', 'choice',
              'Annual Degradation', tooltip=
              'Cara menentukan SOH BESS per tahun. Annual Degradation: SOH = '
              '(1 − degradasi)^umur. SOH Curve (Excel): SOH per tahun dari '
              'berkas Excel/CSV 2 kolom (kolom 1 = tahun/umur, kolom 2 = SOH).',
              choices=['Annual Degradation', 'SOH Curve (Excel)']),
        Param('bess_degradation', 'BESS Degradation per Year', 'float', 0.02,
              '%/yr', 'Degradasi kapasitas tahunan (analisis finansial)', 0.0, 0.2),
        Param('bess_soh_curve', 'BESS SOH Curve', 'soh_curve', [], tooltip=
              'Tabel SOH per tahun (umur BESS) dari berkas Excel/CSV: kolom '
              'pertama = tahun (End of Year, 0 = baru), kolom kedua = SOH '
              '(mis. 94.2% / 0.942 / 94.2). Umur di antara titik diinterpolasi '
              'linear; di luar tabel diekstrapolasi dengan laju tahun terakhir. '
              'Setelah penggantian BESS, kurva dimulai lagi dari tahun 0.'),
    ],
    'Optimization Constraints': [
        Param('max_pv_excess_ratio', 'Maximum Unused Energy (Curtailment)',
              'float', 1.0, '%',
              'Rasio energi PV tak terpakai terhadap produksi ENetAC — '
              'istilah PVsyst: Unused Energy / EUnused (ENetAC yang tidak '
              'tersalurkan melalui inverter)', 0.0, 1.0),
        Param('min_renewable_fraction', 'Minimum Renewable Fraction', 'float',
              0.0, '%', 'Fraksi beban dilayani PV+BESS', 0.0, 1.0),
        Param('max_lcoe', 'Maximum LCOE', 'float', 0.0, 'Rp/kWh',
              '0 = tidak dibatasi', 0.0, 1e6),
        Param('max_capex', 'Maximum CAPEX', 'float', 0.0, 'Rp',
              '0 = tidak dibatasi', 0.0, 1e15),
        Param('max_diesel_fuel_l', 'Maximum Diesel Consumption', 'float', 0.0,
              'L/yr', '0 = tidak dibatasi', 0.0, 1e9),
        Param('target_diesel_reduction', 'Target Diesel Reduction', 'float',
              0.0, '%', 'Reduksi fuel vs skenario diesel-only', 0.0, 1.0),
    ],
}


LANG_DEFAULT = 'ID'


def defaults() -> dict:
    d = {p.key: (list(p.default) if isinstance(p.default, list) else p.default)
         for group in SCHEMA.values() for p in group
         if p.dtype != 'heading'}     # judul sub-bagian bukan parameter
    d['language'] = LANG_DEFAULT      # tidak ditampilkan di halaman Parameters
    return d


def deg_fuel_rates(cfg: dict) -> tuple:
    """Laju konsumsi bahan bakar per-DEG (L/kWh) sebagai (r1, r2, r3).

    Fuel (L) = laju × energi DEG (kWh) — konversi langsung, tanpa faktor kalor.
    Kompatibel-mundur: bila config lama hanya punya `deg_efficiency`, laju
    diturunkan sebagai 1/(eff × 10) agar hasil identik dengan model lama.
    """
    if any(k in cfg for k in
           ('deg1_fuel_rate', 'deg2_fuel_rate', 'deg3_fuel_rate')):
        r1 = float(cfg.get('deg1_fuel_rate', DEFAULT_FUEL_RATE))
        r2 = float(cfg.get('deg2_fuel_rate', r1))
        r3 = float(cfg.get('deg3_fuel_rate', r1))
        return (r1, r2, r3)
    try:
        eff = float(cfg.get('deg_efficiency', 0.33)) or 0.33
    except (TypeError, ValueError):
        eff = 0.33
    r = 1.0 / (eff * 10.0)
    return (r, r, r)


def deg_fuel_rate_eff(cfg: dict) -> float:
    """Laju bahan bakar efektif (skalar) untuk skenario *baseline* diesel yang
    tidak memiliki rincian energi per-DEG (mis. baseline diesel-only). Dihitung
    sebagai rata-rata laju per-DEG berbobot kapasitas DEG aktif; bila semua
    laju sama, hasilnya sama dengan laju tunggal (menjaga kompatibilitas)."""
    rates = deg_fuel_rates(cfg)
    n = _n_deg(cfg)
    caps = [float(cfg.get('deg1_kw', 0.0) or 0.0),
            float(cfg.get('deg2_kw', 0.0) or 0.0),
            float(cfg.get('deg3_kw', 0.0) or 0.0)]
    caps = [caps[i] if i < n else 0.0 for i in range(3)]
    tot = sum(caps)
    if tot > 0:
        return sum(c * r for c, r in zip(caps, rates)) / tot
    return rates[0]


def migrate_cfg(cfg: dict) -> dict:
    """Perbarui config lama secara in-place: efisiensi generator tunggal
    (`deg_efficiency`) → laju konsumsi bahan bakar per-DEG (L/kWh). Aman
    dipanggil berulang dan pada config yang sudah baru."""
    if not isinstance(cfg, dict):
        return cfg
    has_new = any(k in cfg for k in
                  ('deg1_fuel_rate', 'deg2_fuel_rate', 'deg3_fuel_rate'))
    if not has_new and 'deg_efficiency' in cfg:
        try:
            eff = float(cfg.get('deg_efficiency')) or 0.33
        except (TypeError, ValueError):
            eff = 0.33
        r = round(1.0 / (eff * 10.0), 6)
        cfg['deg1_fuel_rate'] = r
        cfg['deg2_fuel_rate'] = r
        cfg['deg3_fuel_rate'] = r
    cfg.pop('deg_efficiency', None)      # buang kunci warisan
    # 'Fixed CAPEX' lama -> 'Accessories Cost' agar total CAPEX proyek terjaga
    if 'fixed_capex' in cfg:
        if 'accessories_cost' not in cfg:
            try:
                cfg['accessories_cost'] = float(cfg.get('fixed_capex') or 0.0)
            except (TypeError, ValueError):
                pass
        cfg.pop('fixed_capex', None)
    return cfg


def load_config(path: str) -> dict:
    cfg = defaults()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            migrate_cfg(raw)             # naikkan config lama sebelum digabung
            cfg.update(raw)
        except Exception:
            pass
    cfg.setdefault('language', LANG_DEFAULT)
    return cfg


def save_config(path: str, cfg: dict):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def to_system_params(cfg: dict):
    """Konversi dict konfigurasi GUI -> SystemParams engine."""
    from ..engine.dispatch import SystemParams
    n = int(cfg.get('deg_count', '1') if str(cfg.get('deg_count', '1')).isdigit() else 1)
    deg = [cfg['deg1_kw'], cfg['deg2_kw'], cfg['deg3_kw']]
    lmax = _deg_lmax(cfg)
    degmax = [lmax, lmax, lmax]
    for i in range(3):
        if i >= n:
            deg[i] = 0.0
            degmax[i] = 0.0
    # Tanpa grid, status grid tak pernah berubah -> fitur "follows grid status"
    # dan interlock DEG-grid tak berlaku; load priority memakai pemetaan
    # grid-padam (posisi 'Grid' dalam rantai tak berpengaruh).
    grid_on = bool(cfg['grid_enabled'])
    lp_code = _prio_code(cfg) if grid_on else _off_code(
        cfg.get('load_priority', ''), cfg)
    return SystemParams(
        pv_kwp=cfg['pv_kwp'], pv_inv_kw=cfg['pv_inv_kw'],
        pv_base_annual=cfg['pv_base_annual'], pv_degradation=cfg['pv_degradation'],
        bess_kwh=cfg['bess_kwh'], soc_init=cfg['soc_init'],
        soc_min=cfg['soc_min'], soc_max=cfg['soc_max'], rte=cfg['rte'],
        max_charge_kw=cfg['max_charge_kw'], max_discharge_kw=cfg['max_discharge_kw'],
        charge_from_grid_below_soc=cfg['charge_from_grid_below_soc'],
        bess_degradation=cfg['bess_degradation'],
        bess_self_cons_kw=_fnum(cfg, 'bess_self_cons_kw', 0.0),
        bess_sc_source=_sc_source_code(cfg),
        grid_enabled=grid_on, grid_kw=cfg['grid_kw'],
        grid_min_loading=cfg['grid_min_loading'],
        grid_max_loading=cfg['grid_max_loading'],
        allow_export=bool(cfg['allow_export']),
        load_priority=lp_code,
        load_priority_split=bool(cfg.get('load_priority_split', False)) and grid_on,
        load_priority_on=_prio_code(
            {**cfg, 'load_priority': cfg.get('load_priority_on',
                                             'Grid -> PV -> BESS -> DEG')}),
        load_priority_off=_off_code(
            cfg.get('load_priority_off', 'PV -> BESS -> DEG'), cfg),
        charge_priority=_prio(cfg['charge_priority']),
        strict_charge_priority=bool(cfg.get('strict_charge_priority', False)),
        grid_charge_enabled=grid_charge_allowed(cfg),
        deg_charge_enabled=bool(cfg['deg_charge_enabled'])
            and not bool(cfg['deg_interlock']),
        deg_interlock=bool(cfg['deg_interlock']),
        deg_sync=bool(cfg.get('deg_sync', True)),
        deg_always=bool(cfg.get('deg_always', False)),
        deg_grid_former=_deg_gridformer_code(cfg),
        deg_options_split=bool(cfg.get('deg_options_split', False)) and grid_on,
        deg_interlock_on=bool(cfg.get('deg_interlock_on', True)),
        deg_interlock_off=bool(cfg.get('deg_interlock_off', True)),
        deg_charge_on=bool(cfg.get('deg_charge_on', False)),
        deg_charge_off=bool(cfg.get('deg_charge_off', False)),
        grid_interlock=grid_interlock_active(cfg),
        deg_grid_interlock=bool(cfg.get('deg_grid_interlock', True)) and grid_on,
        deg_min_loading=float(cfg.get('deg_min_loading', 0.0)),
        deg_kw=tuple(deg), deg_max_loading=tuple(degmax),
        interval_h=_sim_dt_h(cfg),
        **_bess_adv(cfg))




def _sc_source_code(cfg: dict) -> int:
    """Pemasok self consumption BESS: 0 = PV+BESS (baku), 1 = DEG/Grid."""
    v = str(cfg.get('bess_sc_source', 'PV+BESS')).strip().upper()
    return 1 if (v.startswith('DEG') or v.startswith('GRID')) else 0


def parse_soh_curve(rows) -> list:
    """Bersihkan tabel SOH [(tahun, soh), ...] → [[tahun, soh_fraksi], ...]
    terurut menurut tahun. SOH boleh '94.2%', 0.942, atau 94.2 (persen).
    Baris tak numerik (judul) dilewati. Tahun 0 = 100% bila tak ada."""
    out = {}
    for r in rows or []:
        try:
            y, v = r[0], r[1]
        except (TypeError, IndexError, KeyError):
            continue
        try:
            y = float(str(y).strip().replace(',', '.'))
        except (TypeError, ValueError):
            continue
        if y != y or y < 0:
            continue
        pct = False
        if isinstance(v, str):
            t = v.strip().replace(' ', '')
            pct = t.endswith('%')
            t = t.rstrip('%').replace(',', '.')
            try:
                v = float(t)
            except ValueError:
                continue
        else:
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
        if v != v:
            continue
        if pct or v > 1.5:
            v = v / 100.0
        out[round(y, 6)] = max(0.0, min(1.5, v))
    if not out:
        return []
    if 0.0 not in out:
        out[0.0] = 1.0
    return [[float(k), float(out[k])] for k in sorted(out)]


def soh_from_curve(curve, age: float) -> float:
    """SOH pada umur `age` (tahun) dari kurva [[tahun, soh], ...]: interpolasi
    linear; di luar tabel diekstrapolasi dgn laju (rasio) tahun terakhir."""
    pts = parse_soh_curve(curve)
    if not pts:
        return 1.0
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    a = float(age)
    if a <= xs[0]:
        return ys[0]
    if a <= xs[-1]:
        for i in range(1, len(xs)):
            if a <= xs[i]:
                x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
                return y0 + (y1 - y0) * (a - x0) / max(1e-12, x1 - x0)
    if len(xs) >= 2 and ys[-2] > 0 and xs[-1] > xs[-2]:
        r = (ys[-1] / ys[-2]) ** (1.0 / (xs[-1] - xs[-2]))
        return max(0.0, ys[-1] * r ** (a - xs[-1]))
    return ys[-1]


def soh_curve_active(cfg: dict) -> bool:
    return (str(cfg.get('bess_soh_source', 'Annual Degradation')).lower()
            .startswith('soh') and bool(parse_soh_curve(cfg.get('bess_soh_curve'))))


def _deg_lmax(cfg: dict) -> float:
    """Max loading seragam semua DEG; fallback ke deg1_max config lama."""
    return float(cfg.get('deg_max_loading', cfg.get('deg1_max', 1.0)))

def _sim_dt_h(cfg: dict) -> float:
    """dt (jam) satu langkah simulasi dari pilihan 'sim_interval' (default 1 jam).
    Optimization & Multi-Year memakai 1.0 langsung (basis tahunan)."""
    from .intervals import interval_dt_h
    return interval_dt_h(str(cfg.get('sim_interval', '1 hour')))


def _bess_mode_code(cfg: dict) -> int:
    """0 = Standard (jalur Excel murni), 1 = Advanced (fungsi BESS aktif)."""
    return 1 if str(cfg.get('bess_mode', 'Standard')
                    ).strip().lower().startswith('adv') else 0


def _fnum(cfg: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(cfg.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _pi(cfg: dict, key: str, default: int) -> int:
    """Nomor prioritas mode (dropdown '1'..'7') -> int."""
    try:
        return int(cfg.get(key, default))
    except (TypeError, ValueError):
        return int(default)


def _target_code(cfg: dict) -> int:
    """Kode target discharge mode Advanced: 0=Both, 1=Grid, 2=DEG."""
    v = str(cfg.get('adv_target', 'Both')).strip().lower()
    return 1 if v == 'grid' else (2 if v == 'deg' else 0)


def _bess_adv(cfg: dict) -> dict:
    """Bangun field EMS BESS multi-mode untuk SystemParams. Semua di-NOL-kan
    bila mode BUKAN Advanced atau mode terkait mati → engine no-op (Standard
    tetap bit-identik). Param tiap mode hanya diteruskan bila modenya aktif."""
    adv = _bess_mode_code(cfg) == 1

    def mf(key):                     # flag mode (hanya bila Advanced)
        return 1 if (adv and bool(cfg.get(key, False))) else 0

    def mp(mode_key, param_key, lo=0.0, hi=None):   # param mode (bila aktif)
        if not (adv and bool(cfg.get(mode_key, False))):
            return 0.0
        v = max(lo, _fnum(cfg, param_key))
        return min(hi, v) if hi is not None else v

    return dict(
        bess_mode=1 if adv else 0,
        adv_target=(_target_code(cfg) if adv else 0),
        m_pv_smooth=mf('m_pv_smooth'), m_firming=mf('m_firming'),
        m_load_shift=mf('m_load_shift'), m_peak_shave=mf('m_peak_shave'),
        m_dg_minload=mf('m_dg_minload'),
        m_reserve=mf('m_reserve'), m_backup=mf('m_backup'),
        peak_shave_kw=mp('m_peak_shave', 'peak_shave_kw'),
        firming_kw=mp('m_firming', 'firming_kw'),
        firming_trigger=((1 if str(cfg.get('firming_trigger', 'PV Power'))
                          .strip().lower().startswith('time') else 0)
                         if (adv and cfg.get('m_firming')) else 0),
        firming_pv_start=mp('m_firming', 'firming_pv_start'),
        firming_pv_end=mp('m_firming', 'firming_pv_end'),
        firming_time_start=mp('m_firming', 'firming_time_start', 0.0, 24.0),
        firming_time_end=mp('m_firming', 'firming_time_end', 0.0, 24.0),
        arb_peak_start=(_fnum(cfg, 'arb_peak_start', 18.0)
                        if (adv and cfg.get('m_load_shift')) else 0.0),
        arb_peak_end=(_fnum(cfg, 'arb_peak_end', 22.0)
                      if (adv and cfg.get('m_load_shift')) else 0.0),
        pv_ramp_up_kwmin=mp('m_pv_smooth', 'pv_ramp_up_kwmin'),
        pv_ramp_dn_kwmin=mp('m_pv_smooth', 'pv_ramp_dn_kwmin'),
        smoothing_window=(max(1, int(_fnum(cfg, 'smoothing_window', 10)))
                          if (adv and cfg.get('m_pv_smooth')) else 1),
        reserve_frac=mp('m_reserve', 'reserve_frac', 0.0, 100.0) / 100.0,
        reserve_kw=mp('m_reserve', 'reserve_kw'),
        prio_pv_smooth=_pi(cfg, 'prio_pv_smooth', 2),
        prio_firming=_pi(cfg, 'prio_firming', 2),
        prio_load_shift=_pi(cfg, 'prio_load_shift', 4),
        prio_peak_shave=_pi(cfg, 'prio_peak_shave', 5),
        prio_dg_minload=_pi(cfg, 'prio_dg_minload', 3),
        prio_reserve=_pi(cfg, 'prio_reserve', 1),
        prio_backup=_pi(cfg, 'prio_backup', 1))


def _deg_gridformer_code(cfg: dict) -> int:
    """Kode DEG grid-forming (must-run) pilihan pengguna:
    0 = Auto (genset terkecil), 1/2/3 = DEG-1/2/3. Nilai tak dikenal -> 0."""
    v = str(cfg.get('deg_grid_former', 'Auto')).strip().upper()
    if v.startswith('DEG-') or v.startswith('DEG '):
        try:
            k = int(''.join(ch for ch in v if ch.isdigit()))
            return k if k in (1, 2, 3) else 0
        except Exception:
            return 0
    return 0

def _prio(val: str) -> float:
    """Kode mode prioritas beban (parser warisan untuk label lama):
    0 = PV -> Grid -> ..., 1 = Grid dahulu, 2 = PV -> BESS -> Grid.
    Aman terhadap label tanpa '->' (mis. label deskriptif baru)."""
    t = ' '.join(str(val).upper().split())
    if t.startswith('GRID'):
        return 1.0
    parts = t.split('->')
    seg = parts[1] if len(parts) > 1 else t
    return 2.0 if 'BESS' in seg else 0.0


def grid_interlock_active(cfg: dict) -> bool:
    """Interlock grid hanya berlaku bila mode prioritas beban memisahkan
    grid dari PV-BESS. Mode PV-dahulu (kode 0) & Auto (kode 4) mencampur
    keduanya, jadi interlock otomatis dinonaktifkan di sana."""
    if not bool(cfg.get('grid_interlock', False)):
        return False
    return _prio_code(cfg) not in (0.0, 4.0)


def grid_charge_allowed(cfg: dict) -> bool:
    """Grid tidak dapat mengisi BESS saat bus grid ter-interlock."""
    return bool(cfg.get('grid_charge_enabled', True)) \
        and not grid_interlock_active(cfg)



# Label mode 'Auto by Grid Status' (kode 4). Strategi berpindah otomatis:
#   Grid ON  -> Grid -> DEG -> PV -> BESS  (charge Grid -> PV)
#   Grid OFF -> PV -> BESS -> DEG          (charge PV, DEG interlock PV-BESS)
# Label ringkas (rincian rantai dijelaskan di tooltip). Kode 4 = strategi
# yang berpindah otomatis menurut status grid.
AUTO_LABEL = 'Auto by Grid Status'
# Kode 5: Grid -> PV -> BESS -> DEG dengan interlock DEG↔PV-BESS yang hanya
# aktif saat grid padam (saat grid ada, DEG paralel penuh).
AUTO_INTERLOCK_LABEL = 'Grid -> PV -> BESS -> DEG (auto-interlock)'


# Rantai prioritas beban: label berubah mengikuti opsi DEG Interlock with Grid.
# Kode internal tetap sama (0 = PV dahulu, 1 = Grid dahulu, 2 = PV→BESS dahulu)
# sehingga berkas proyek lama tetap terbaca.
# Label deskriptif per kode. Tuple = (varian saat DEG interlock grid,
# varian saat DEG boleh paralel grid). Teks boleh membungkus di popup;
# lebar combo dibatasi sehingga layout tidak melebar (lihat WrapComboBox).
# Pemetaan label→kode memakai pencocokan tepat (lihat _prio_code), sehingga
# teks deskriptif bebas tanpa mengganggu logika.
PRIORITY_CHAINS = {
    0.0: ('PV -> Grid -> BESS -> DEG', 'PV -> Grid -> DEG -> BESS'),
    1.0: ('Grid -> PV -> BESS -> DEG', 'Grid -> DEG -> PV -> BESS'),
    2.0: ('PV -> BESS -> Grid -> DEG', 'PV -> BESS -> Grid -> DEG'),
    # Kode 3/4/5 hanya muncul saat DEG boleh paralel grid (interlock grid off).
    3.0: ('Grid -> PV -> BESS -> DEG', 'Grid -> PV -> BESS -> DEG'),
    4.0: (AUTO_LABEL, AUTO_LABEL),
    5.0: (AUTO_INTERLOCK_LABEL, AUTO_INTERLOCK_LABEL),
}


def _deg_parallel_grid(cfg: dict) -> bool:
    """Genset boleh beroperasi paralel dengan grid?"""
    return (bool(cfg.get('grid_enabled', True))
            and _n_deg(cfg) > 0
            and not bool(cfg.get('deg_grid_interlock', True)))


def _prio_code(cfg: dict) -> float:
    """Kode mode prioritas beban untuk engine, DENGAN konteks konfigurasi.

    Sama seperti _prio(), tetapi saat DEG boleh paralel grid (DEG Interlock
    with Grid nonaktif) opsi grid-dahulu terpecah menjadi dua rantai yang
    berbeda:
      'Grid -> DEG -> PV -> BESS'  -> genset naik sebelum PV/BESS (kode 1)
      'Grid -> PV -> BESS -> DEG'  -> genset cadangan TERAKHIR namun boleh
                                      menyala paralel grid              (kode 3)
    Berkas proyek lama tidak terpengaruh: labelnya selalu terpetakan ke
    kode yang sama seperti sebelumnya.

    Kode 4 = mode 'Auto by Grid Status': strategi berubah menurut status
    grid tiap jam (butuh grid aktif + ada DEG).

    Label 'Grid -> PV -> BESS -> DEG' dipetakan ke kode 3 saat DEG boleh
    paralel grid, atau kode 1 bila tidak — dibedakan lewat konteks, bukan
    teks. Kode 5 dikenali dari penanda '(auto-interlock)'."""
    s = ' '.join(str(cfg.get('load_priority', '')).upper().split())
    grid_deg = bool(cfg.get('grid_enabled', True)) and _n_deg(cfg) > 0
    if s.startswith('AUTO') and grid_deg:
        return 4.0
    base = _prio(cfg.get('load_priority', ''))
    if base == 1.0 and _deg_parallel_grid(cfg):
        if 'INTERLOCK' in s:               # 'Grid -> PV -> BESS -> DEG (auto-interlock)'
            return 5.0
        seg = s.split('->')
        if len(seg) > 1 and 'DEG' not in seg[1]:   # 'Grid -> PV -> ...'
            return 3.0
    return base


def load_priority_choices(cfg: dict) -> list:
    """Pilihan Load Supply Priority sesuai konfigurasi saat ini.
    Saat DEG boleh paralel grid, opsi 'Grid -> PV -> BESS -> DEG' (kode 3)
    ikut ditawarkan di samping 'Grid -> DEG -> PV -> BESS' (kode 1)."""
    parallel = _deg_parallel_grid(cfg)
    i = 1 if parallel else 0
    codes = (0.0, 1.0, 3.0, 5.0, 4.0, 2.0) if parallel else (0.0, 1.0, 2.0)
    out = []
    for code in codes:
        lbl = PRIORITY_CHAINS[code][i]
        if lbl not in out:
            out.append(lbl)
    return out


def load_priority_base_choices(cfg: dict) -> list:
    """Pilihan rantai DASAR (tanpa mode komposit 'Auto by Grid Status' /
    '(auto-interlock)') — dipakai untuk skenario per status grid, di mana
    komposit tidak relevan (statusnya sudah dipisah)."""
    return [c for c in load_priority_choices(cfg)
            if c not in (AUTO_LABEL, AUTO_INTERLOCK_LABEL)]


def load_priority_label(value, cfg: dict) -> str:
    """Terjemahkan nilai tersimpan ke label rantai yang berlaku."""
    code = _prio_code({**cfg, 'load_priority': value})
    i = 1 if _deg_parallel_grid(cfg) else 0
    return PRIORITY_CHAINS.get(code, PRIORITY_CHAINS[0.0])[i]


# ---- Skenario khusus saat GRID PADAM (status 0) ----------------------------
# Saat grid tidak tersedia, grid memasok 0 kW sehingga posisi 'Grid' dalam
# rantai tak berpengaruh: rantai yang hanya berbeda pada letak Grid menjadi
# IDENTIK saat padam. Karena itu selektor 'Grid Unavailable (0)' cukup
# menampilkan strategi grid-padam yang benar-benar berbeda — urutan PV/BESS/DEG
# saja:
#   'PV -> BESS -> DEG'  (DEG cadangan terakhir)  -> kode 2  (== kode 3 saat padam)
#   'PV -> DEG -> BESS'  (DEG naik sebelum BESS)  -> kode 0
#   'DEG -> PV -> BESS'  (DEG lebih dulu)         -> kode 1
# Dua terakhir hanya relevan saat DEG boleh paralel grid (DEG Interlock with
# Grid nonaktif). Bila interlock grid aktif, ketiga rantai dasar sama-sama
# menjadi 'PV -> BESS -> DEG' saat padam, jadi hanya satu opsi ditampilkan.
OFF_CHAINS = {
    2.0: 'PV -> BESS -> DEG',
    0.0: 'PV -> DEG -> BESS',
    1.0: 'DEG -> PV -> BESS',
}


def load_priority_off_choices(cfg: dict) -> list:
    """Pilihan skenario prioritas beban saat GRID PADAM (status 0), diringkas
    ke strategi yang benar-benar berbeda (posisi 'Grid' tak berpengaruh)."""
    codes = (2.0, 0.0, 1.0) if _deg_parallel_grid(cfg) else (2.0,)
    return [OFF_CHAINS[c] for c in codes]


def _off_code(value, cfg: dict) -> float:
    """Kode engine untuk skenario grid-padam. Menerima label ringkas baru
    ('PV -> BESS -> DEG', dst.) MAUPUN label rantai penuh lama
    ('Grid -> PV -> BESS -> DEG', dst.) demi kompatibilitas berkas lama —
    setiap rantai penuh dipetakan ke perilaku grid-padam-nya."""
    s = ' '.join(str(value).upper().split())
    for code, lbl in OFF_CHAINS.items():
        if s == lbl.upper():
            return code
    # label lama (rantai penuh): pakai kode kontekstual lalu petakan ke
    # perilaku saat grid padam (grid = 0 kW).
    code = _prio_code({**cfg, 'load_priority': value})
    if not _deg_parallel_grid(cfg):
        return 2.0                       # semua -> PV -> BESS -> DEG saat padam
    return {0.0: 0.0, 1.0: 1.0, 2.0: 2.0,
            3.0: 2.0, 5.0: 2.0}.get(code, 2.0)


def load_priority_off_label(value, cfg: dict) -> str:
    """Label ringkas grid-padam untuk nilai tersimpan (baru atau lama)."""
    return OFF_CHAINS[_off_code(value, cfg)]


def load_priority_offgrid_choices(cfg: dict) -> list:
    """Pilihan Load Supply Priority untuk sistem TANPA grid (Any Grid
    Connection nonaktif). Grid tak ada, jadi rantai hanya menyangkut urutan
    PV/BESS/DEG. Bila ada genset, ketiga strategi ditawarkan (genset boleh
    naik sebelum BESS); tanpa genset hanya PV -> BESS."""
    if _n_deg(cfg) > 0:
        return [OFF_CHAINS[c] for c in (2.0, 0.0, 1.0)]
    return [OFF_CHAINS[2.0]]


def load_priority_groups(cfg: dict) -> list:
    """Susunan berkelompok untuk dropdown Load Supply Priority, dibagi menurut
    status grid: kelompok 'Grid Status 1' (grid sebagai sumber utama —
    rantai yang diawali Grid + mode adaptif) dan 'Grid Status 0'
    (PV/BESS diprioritaskan — rantai yang diawali PV).

    Mengembalikan [(judul_kelompok, [label, ...]), ...] mengikuti opsi yang
    berlaku pada konfigurasi saat ini (mis. kode 3/4/5 hanya saat DEG boleh
    paralel grid)."""
    parallel = _deg_parallel_grid(cfg)
    i = 1 if parallel else 0
    if parallel:
        g1_codes = (1.0, 3.0, 5.0, 4.0)      # Grid dahulu + adaptif
        g0_codes = (0.0, 2.0)                # PV dahulu
    else:
        g1_codes = (1.0,)
        g0_codes = (0.0, 2.0)
    g1 = [PRIORITY_CHAINS[c][i] for c in g1_codes]
    g0 = [PRIORITY_CHAINS[c][i] for c in g0_codes]
    return [('Grid Status 1 — grid tersedia', g1),
            ('Grid Status 0 — grid padam', g0)]



PRIORITY_HELP = {
    'PV -> Grid -> BESS -> DEG':
        'PV melayani beban lebih dulu (menyisakan minimum loading untuk '
        'grid); grid memikul sisanya; BESS hanya menutup kekurangan yang '
        'melebihi kapasitas grid; genset menjadi cadangan terakhir.',
    'PV -> Grid -> DEG -> BESS':
        'PV melayani beban lebih dulu; grid memikul sisanya sampai batas '
        'kapasitasnya; genset menutup kekurangan berikutnya (boleh paralel '
        'dengan grid); BESS menjadi cadangan terakhir.',
    'Grid -> PV -> BESS -> DEG':
        'Grid memikul beban lebih dulu hingga batas loading maksimumnya; '
        'PV lalu BESS menutup sisanya; genset menjadi cadangan terakhir.',
    'Grid -> DEG -> PV -> BESS':
        'Grid memikul beban lebih dulu; genset langsung menutup kekurangan '
        'yang tidak sanggup dipikul grid (boleh paralel); PV lalu BESS '
        'melayani sisanya.',
    'PV -> BESS -> Grid -> DEG':
        'PV lalu BESS melayani beban lebih dulu (menyisakan minimum loading '
        'untuk grid); grid mengambil sisanya; genset menjadi cadangan '
        'terakhir. Cocok untuk memaksimalkan pemakaian energi surya.',
}


def load_priority_help(value, cfg: dict) -> str:
    """Penjelasan rantai prioritas yang sedang dipilih."""
    if _prio_code({**cfg, 'load_priority': value}) == 4.0:
        return ('Strategi otomatis mengikuti status grid tiap jam. '
                'Grid TERSEDIA: beban dilayani Grid → DEG → PV → BESS '
                '(genset membantu bila beban melebihi grid), pengisian BESS '
                'Grid → PV (sisa kapasitas grid mengisi BESS hingga ambang '
                '"Charge from Grid below SOC"); grid, DEG, PV, dan BESS boleh '
                'paralel. Grid PADAM: beban dilayani PV → BESS → DEG dengan '
                'DEG interlock PV-BESS (saat genset menyala ia memikul '
                'seluruh beban, PV hanya mengisi BESS). Membutuhkan grid '
                'aktif, ada DEG, dan DEG tidak interlock dengan grid.')
    if _prio_code({**cfg, 'load_priority': value}) == 5.0:
        return ('Beban dilayani Grid → PV → BESS → DEG. Saat grid TERSEDIA: '
                'genset boleh menyala paralel dengan Grid maupun PV-BESS '
                '(hanya menutup kekurangan yang tak sanggup dipikul '
                'grid + PV + BESS). Saat grid PADAM: DEG interlock dengan '
                'PV-BESS — begitu genset menyala ia memikul SELURUH beban, '
                'PV hanya mengisi BESS, dan BESS tidak discharge. '
                'Membutuhkan grid aktif, ada DEG, dan DEG tidak interlock '
                'dengan grid.')
    if _prio_code({**cfg, 'load_priority': value}) == 3.0:
        return ('Grid memikul beban lebih dulu (hormati batas loading); PV '
                'lalu BESS menutup sisanya; genset menjadi cadangan TERAKHIR '
                'namun boleh menyala paralel dengan grid untuk menutup '
                'kekurangan yang tidak sanggup dipikul grid + PV + BESS.')
    # Kode 0/1/2: bantuan dipetakan berdasarkan KODE (label tampilan boleh
    # deskriptif) ke kunci PRIORITY_HELP yang punya terjemahan EN.
    code = _prio_code({**cfg, 'load_priority': value})
    idx = 1 if _deg_parallel_grid(cfg) else 0
    key = _HELP_KEY.get(code, _HELP_KEY[0.0])[idx]
    return PRIORITY_HELP.get(key, '')


# Kode prioritas -> kunci teks bantuan (varian interlock-grid, paralel-grid).
_HELP_KEY = {
    0.0: ('PV -> Grid -> BESS -> DEG', 'PV -> Grid -> DEG -> BESS'),
    1.0: ('Grid -> PV -> BESS -> DEG', 'Grid -> DEG -> PV -> BESS'),
    2.0: ('PV -> BESS -> Grid -> DEG', 'PV -> BESS -> Grid -> DEG'),
}


def opt_base_params(cfg: dict) -> dict:
    """Parameter dasar (non-sweep) untuk OptimizationEngine dari config GUI."""
    grid_on = bool(cfg.get('grid_enabled', True))
    lp_code = _prio_code(cfg) if grid_on else _off_code(
        cfg.get('load_priority', ''), cfg)
    # Genset dinolkan sesuai jumlah unit (deg_count) — identik dengan
    # to_system_params. Tanpa langkah ini, kapasitas default deg2/deg3 (atau
    # deg1 saat Total DEG = 0) tetap ikut disimulasikan sehingga muncul diesel
    # energy meski pengguna meniadakan genset.
    n = _n_deg(cfg)
    deg = [cfg['deg1_kw'], cfg['deg2_kw'], cfg['deg3_kw']]
    lmax = _deg_lmax(cfg)
    degmax = [lmax, lmax, lmax]
    for i in range(3):
        if i >= n:
            deg[i] = 0.0
            degmax[i] = 0.0
    return dict(
        pv_base_annual=cfg['pv_base_annual'],
        pv_module_wp=cfg.get('pv_module_wp', 0.0),
        soc_init=cfg['soc_init'],
        soc_min=cfg['soc_min'], soc_max=cfg['soc_max'], rte=cfg['rte'],
        bess_c_rate=cfg['max_charge_kw'] / max(cfg['bess_kwh'], 1e-9),
        charge_from_grid_below_soc=cfg['charge_from_grid_below_soc'],
        bess_self_cons_kw=_fnum(cfg, 'bess_self_cons_kw', 0.0),
        bess_sc_source=_sc_source_code(cfg),
        grid_enabled=cfg['grid_enabled'], grid_kw=cfg['grid_kw'],
        grid_min_loading=cfg['grid_min_loading'],
        grid_max_loading=cfg['grid_max_loading'], interval_h=1.0,
        deg_kw=tuple(deg),
        deg_max_loading=(degmax[0], degmax[1]),
        deg_fuel_rate=deg_fuel_rates(cfg),
        deg_fuel_rate_eff=deg_fuel_rate_eff(cfg),
        allow_export=cfg['allow_export'],
        load_priority=lp_code,
        load_priority_split=bool(cfg.get('load_priority_split', False)) and grid_on,
        load_priority_on=_prio_code(
            {**cfg, 'load_priority': cfg.get('load_priority_on',
                                             'Grid -> PV -> BESS -> DEG')}),
        load_priority_off=_off_code(
            cfg.get('load_priority_off', 'PV -> BESS -> DEG'), cfg),
        charge_priority=_prio(cfg['charge_priority']),
        strict_charge_priority=bool(cfg.get('strict_charge_priority', False)),
        grid_charge_enabled=grid_charge_allowed(cfg),
        deg_charge_enabled=bool(cfg['deg_charge_enabled'])
            and not bool(cfg['deg_interlock']),
        deg_interlock=bool(cfg['deg_interlock']),
        deg_sync=bool(cfg.get('deg_sync', True)),
        deg_always=bool(cfg.get('deg_always', False)),
        deg_grid_former=_deg_gridformer_code(cfg),
        deg_options_split=bool(cfg.get('deg_options_split', False)) and grid_on,
        deg_interlock_on=bool(cfg.get('deg_interlock_on', True)),
        deg_interlock_off=bool(cfg.get('deg_interlock_off', True)),
        deg_charge_on=bool(cfg.get('deg_charge_on', False)),
        deg_charge_off=bool(cfg.get('deg_charge_off', False)),
        grid_interlock=grid_interlock_active(cfg),
        deg_grid_interlock=bool(cfg.get('deg_grid_interlock', True)) and grid_on,
        deg_min_loading=float(cfg.get('deg_min_loading', 0.0)),
        **_bess_adv(cfg),
        pv_degradation=cfg['pv_degradation'])


def cost_config(cfg: dict) -> dict:
    return dict(
        pv_cost_per_kwp=cfg['pv_cost_per_kwp'],
        inverter_cost_per_kw=cfg['inverter_cost_per_kw'],
        bess_cost_per_kwh=cfg['bess_cost_per_kwh'],
        deg_cost_per_kw=cfg['deg_cost_per_kw'],
        accessories_cost=cfg.get('accessories_cost', 0.0),
        logistic_cost=cfg.get('logistic_cost', 0.0),
        epc_cost_per_kwp=cfg.get('epc_cost_per_kwp', 0.0),
        om_fraction=cfg['om_fraction'],
        diesel_price_per_l=cfg['diesel_price_per_l'],
        grid_tariff_per_kwh=cfg['grid_tariff_per_kwh'],
        export_tariff_per_kwh=cfg['export_tariff_per_kwh'],
        tariff_offpeak_per_kwh=cfg.get('tariff_offpeak_per_kwh',
                                       cfg['grid_tariff_per_kwh']),
        discount_rate=cfg['discount_rate'], inflation=cfg['inflation'],
        project_lifetime_y=cfg['project_lifetime_y'],
        baseline_mode=cfg['baseline_mode'],
        finance_scope=cfg.get('finance_scope', 'PV-BESS-DEG'),
        deg_fuel_rate=deg_fuel_rates(cfg),
        deg_fuel_rate_eff=deg_fuel_rate_eff(cfg))


def _n_deg(cfg) -> int:
    try:
        return int(str(cfg.get('deg_count', '1')))
    except Exception:
        return 1


def _has(cfg, key, default=0.0) -> bool:
    try:
        return float(cfg.get(key, default)) > 0
    except Exception:
        return True


def _adv_bess(cfg) -> bool:
    """True bila ada baterai & mode BESS = Advanced (untuk visibilitas mode)."""
    return _has(cfg, 'bess_kwh') and cfg.get('bess_mode') == 'Advanced'


VISIBILITY = {
    # ---- Grid: semuanya bergantung ada/tidaknya sambungan grid ----
    'grid_kw':               lambda c: c.get('grid_enabled', True),
    'grid_min_loading':      lambda c: c.get('grid_enabled', True),
    'grid_max_loading':      lambda c: c.get('grid_enabled', True),
    'grid_tariff_per_kwh':   lambda c: c.get('grid_enabled', True),
    'allow_export':          lambda c: c.get('grid_enabled', True),
    'export_tariff_per_kwh': lambda c: c.get('grid_enabled', True)
                                        and c.get('allow_export', False),
    # ---- Dispatch Strategy: mode BESS lanjutan (Advanced) ----
    # Mode, fungsi & target BESS hanya relevan bila ada baterai. Fungsi &
    # target tampil saat mode Advanced; parameter tiap fungsi tampil saat
    # fungsi itu terpilih. Target (Grid/DEG) berlaku untuk keempat fungsi.
    'bess_mode':     lambda c: _has(c, 'bess_kwh'),
    # Judul "BESS Role Function" hanya tampil pada mode Advanced (di atas 8 mode).
    '__hdr_bess_role': lambda c: _adv_bess(c),
    'adv_target': lambda c: _adv_bess(c),
    # Mode BESS = checkbox (tampil bila Advanced & ada baterai); parameter tiap
    # mode tampil hanya saat modenya dicentang.
    'm_pv_smooth':   lambda c: _adv_bess(c),
    'prio_pv_smooth': lambda c: _adv_bess(c) and c.get('m_pv_smooth'),
    'm_firming':     lambda c: _adv_bess(c),
    'prio_firming':  lambda c: _adv_bess(c) and c.get('m_firming'),
    'm_load_shift':  lambda c: _adv_bess(c),
    'prio_load_shift': lambda c: _adv_bess(c) and c.get('m_load_shift'),
    'm_peak_shave':  lambda c: _adv_bess(c),
    'prio_peak_shave': lambda c: _adv_bess(c) and c.get('m_peak_shave'),
    'm_dg_minload':  lambda c: _adv_bess(c) and _n_deg(c) > 0,
    'prio_dg_minload': lambda c: _adv_bess(c) and _n_deg(c) > 0
                                  and c.get('m_dg_minload'),
    'm_reserve':     lambda c: _adv_bess(c),
    'prio_reserve':  lambda c: _adv_bess(c) and c.get('m_reserve'),
    'm_backup':      lambda c: _adv_bess(c),
    'prio_backup':   lambda c: _adv_bess(c) and c.get('m_backup'),
    'pv_ramp_up_kwmin': lambda c: _adv_bess(c) and c.get('m_pv_smooth'),
    'pv_ramp_dn_kwmin': lambda c: _adv_bess(c) and c.get('m_pv_smooth'),
    'smoothing_window': lambda c: _adv_bess(c) and c.get('m_pv_smooth'),
    'firming_kw':     lambda c: _adv_bess(c) and c.get('m_firming'),
    'firming_trigger': lambda c: _adv_bess(c) and c.get('m_firming'),
    'firming_pv_start': lambda c: _adv_bess(c) and c.get('m_firming')
        and not str(c.get('firming_trigger', 'PV Power')).strip().lower().startswith('time'),
    'firming_pv_end': lambda c: _adv_bess(c) and c.get('m_firming')
        and not str(c.get('firming_trigger', 'PV Power')).strip().lower().startswith('time'),
    'firming_time_start': lambda c: _adv_bess(c) and c.get('m_firming')
        and str(c.get('firming_trigger', 'PV Power')).strip().lower().startswith('time'),
    'firming_time_end': lambda c: _adv_bess(c) and c.get('m_firming')
        and str(c.get('firming_trigger', 'PV Power')).strip().lower().startswith('time'),
    'arb_peak_start':      lambda c: _adv_bess(c) and c.get('m_load_shift'),
    'arb_peak_end':        lambda c: _adv_bess(c) and c.get('m_load_shift'),
    'tariff_offpeak_per_kwh': lambda c: _adv_bess(c) and c.get('m_load_shift')
                                         and c.get('grid_enabled', True),
    'peak_shave_kw':  lambda c: _adv_bess(c) and c.get('m_peak_shave'),
    'reserve_frac':   lambda c: _adv_bess(c) and c.get('m_reserve'),
    'reserve_kw':     lambda c: _adv_bess(c) and c.get('m_reserve'),
    # Satu skenario tunggal (saat split nonaktif) ATAU dua skenario per
    # status grid (saat split aktif).
    # Load Supply Priority selalu relevan (urutan PV/BESS/DEG) — termasuk saat
    # TANPA grid. Hanya disembunyikan bila split per-status-grid sedang aktif
    # (yang hanya mungkin ketika grid ada).
    'load_priority':       lambda c: not (c.get('grid_enabled', True)
                                          and c.get('load_priority_split', False)),
    'load_priority_split': lambda c: c.get('grid_enabled', True),
    'load_priority_on':    lambda c: c.get('grid_enabled', True)
                                      and c.get('load_priority_split', False),
    'load_priority_off':   lambda c: c.get('grid_enabled', True)
                                      and c.get('load_priority_split', False),
    'grid_charge_enabled': lambda c: c.get('grid_enabled', True)
                                      and _has(c, 'bess_kwh')
                                      and not grid_interlock_active(c),
    # Mode 'Auto by Grid Status' (kode 4) mengatur sendiri charge priority &
    # interlock per jam, jadi opsi-opsi ini disembunyikan saat mode itu aktif.
    'charge_priority':     lambda c: c.get('grid_enabled', True)
                                      and _has(c, 'bess_kwh')
                                      and c.get('grid_charge_enabled', True)
                                      and _prio_code(c) != 4.0,
    'strict_charge_priority': lambda c: c.get('grid_enabled', True)
                                         and _has(c, 'bess_kwh')
                                         and c.get('grid_charge_enabled', True)
                                         and _prio_code(c) != 4.0,
    # Opsi DEG tunggal (saat split nonaktif) ATAU per status grid (saat aktif).
    # Split hanya "aktif" bila grid ada; tanpa grid, opsi tunggal selalu tampil
    # (mengabaikan nilai split lama yang mungkin tertinggal True).
    'deg_charge_enabled':  lambda c: _n_deg(c) > 0 and _has(c, 'bess_kwh')
                                      and _prio_code(c) not in (4.0, 5.0)
                                      and not (c.get('grid_enabled', True)
                                               and c.get('deg_options_split', False)),
    'deg_interlock':       lambda c: _n_deg(c) > 0
                                      and _prio_code(c) not in (4.0, 5.0)
                                      and not (c.get('grid_enabled', True)
                                               and c.get('deg_options_split', False)),
    'deg_sync':            lambda c: _n_deg(c) > 1,
    'deg_always':          lambda c: _n_deg(c) > 0,
    'deg_grid_former':     lambda c: bool(c.get('deg_always')) and _n_deg(c) > 1,
    'deg_options_split':   lambda c: c.get('grid_enabled', True) and _n_deg(c) > 0
                                      and _prio_code(c) not in (4.0, 5.0),
    'deg_interlock_on':    lambda c: c.get('grid_enabled', True) and _n_deg(c) > 0
                                      and _prio_code(c) not in (4.0, 5.0)
                                      and c.get('deg_options_split', False),
    'deg_interlock_off':   lambda c: c.get('grid_enabled', True) and _n_deg(c) > 0
                                      and _prio_code(c) not in (4.0, 5.0)
                                      and c.get('deg_options_split', False),
    'deg_charge_on':       lambda c: c.get('grid_enabled', True) and _n_deg(c) > 0
                                      and _has(c, 'bess_kwh')
                                      and _prio_code(c) not in (4.0, 5.0)
                                      and c.get('deg_options_split', False),
    'deg_charge_off':      lambda c: c.get('grid_enabled', True) and _n_deg(c) > 0
                                      and _has(c, 'bess_kwh')
                                      and _prio_code(c) not in (4.0, 5.0)
                                      and c.get('deg_options_split', False),
    'deg_grid_interlock':  lambda c: c.get('grid_enabled', True)
                                      and _n_deg(c) > 0
                                      and _prio_code(c) not in (4.0, 5.0),
    'grid_interlock':      lambda c: c.get('grid_enabled', True)
                                      and (_has(c, 'pv_kwp')
                                           or _has(c, 'bess_kwh'))
                                      and _prio_code(c) not in (0.0, 4.0),
    # ---- Diesel: jumlah unit menentukan field kapasitas ----
    'deg1_kw':            lambda c: _n_deg(c) >= 1,
    'deg2_kw':            lambda c: _n_deg(c) >= 2,
    'deg3_kw':            lambda c: _n_deg(c) >= 3,
    'diesel_price_per_l': lambda c: _n_deg(c) > 0,
    'deg_min_loading':    lambda c: _n_deg(c) > 0,
    'deg_max_loading':    lambda c: _n_deg(c) > 0,
    'deg1_fuel_rate':     lambda c: _n_deg(c) >= 1,
    'deg2_fuel_rate':     lambda c: _n_deg(c) >= 2,
    'deg3_fuel_rate':     lambda c: _n_deg(c) >= 3,
    'deg_cost_per_kw':    lambda c: _n_deg(c) > 0,
    # ---- Battery: kapasitas 0 = tanpa BESS ----
    'soc_init':          lambda c: _has(c, 'bess_kwh'),
    'soc_min':           lambda c: _has(c, 'bess_kwh'),
    'soc_max':           lambda c: _has(c, 'bess_kwh'),
    'rte':               lambda c: _has(c, 'bess_kwh'),
    'max_charge_kw':     lambda c: _has(c, 'bess_kwh'),
    'max_discharge_kw':  lambda c: _has(c, 'bess_kwh'),
    'bess_degradation':  lambda c: _has(c, 'bess_kwh') and not str(
        c.get('bess_soh_source', '')).lower().startswith('soh'),
    'bess_soh_source':   lambda c: _has(c, 'bess_kwh'),
    'bess_soh_curve':    lambda c: _has(c, 'bess_kwh') and str(
        c.get('bess_soh_source', '')).lower().startswith('soh'),
    'bess_self_cons_kw': lambda c: _has(c, 'bess_kwh'),
    'bess_sc_source':    lambda c: _has(c, 'bess_kwh')
                                   and _fnum(c, 'bess_self_cons_kw', 0.0) > 0,
    'bess_lifetime_y':   lambda c: _has(c, 'bess_kwh'),
    'bess_soh_threshold': lambda c: _has(c, 'bess_kwh'),
    'bess_cost_per_kwh': lambda c: _has(c, 'bess_kwh'),
    'charge_from_grid_below_soc': lambda c: _has(c, 'bess_kwh')
                                             and c.get('grid_enabled', True)
                                             and c.get('grid_charge_enabled', True),
    # ---- PV: kapasitas 0 = tanpa PV ----
    'pv_module_wp':         lambda c: _has(c, 'pv_kwp'),
    'pv_inv_kw':            lambda c: _has(c, 'pv_kwp'),
    'pv_degradation':       lambda c: _has(c, 'pv_kwp'),
    'pv_base_annual':       lambda c: _has(c, 'pv_kwp'),
    'pv_cost_per_kwp':      lambda c: _has(c, 'pv_kwp'),
    'inverter_cost_per_kw': lambda c: _has(c, 'pv_kwp'),
}


# --- "Base Parameters" (dulu "Base Dispatch & Sources") SELALU tampil, baik
#     mode Standard MAUPUN Advanced -- ini parameter dasar (Load Supply
#     Priority, interlock DEG/Grid, DEG Must Always Run, Charging Priority,
#     dst.) yg jadi FONDASI dispatch fisik utk KEDUA mode; mode Advanced
#     (BESS Role Function/EMS) bekerja DI ATAS fondasi ini, bukan
#     menggantikannya. SEBELUMNYA section ini secara keliru disembunyikan
#     total saat Advanced aktif (lihat riwayat) -- pengguna jadi tak bisa
#     melihat/mengubah mis. DEG Interlock with PV-BESS sama sekali ketika di
#     mode Advanced, padahal parameter itu tetap dipakai mesin dispatch dgn
#     nilai (default/tersimpan) apa adanya secara diam-diam. Sudah dibetulkan:
#     TIDAK ADA lagi pembungkusan visibilitas berbasis _adv_bess di sini --
#     tiap kunci di section ini memakai aturan visibilitasnya sendiri saja
#     (mis. _n_deg(c)>0, grid_enabled, dst., didefinisikan di atas), yg
#     berlaku SAMA di mode Standard maupun Advanced.
