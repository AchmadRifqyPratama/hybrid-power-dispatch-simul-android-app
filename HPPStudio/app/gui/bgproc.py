"""Pekerja latar berbasis PROSES (bukan thread) untuk simulasi/optimasi.

Mengapa proses?
    Engine dispatch berjalan di Python. Di QThread, engine berebut GIL dengan
    thread GUI sehingga UI tersendat (terukur: event loop macet hingga ~3 dtk)
    dan simulasi sendiri melambat (~5x). Di proses terpisah, GUI tetap bebas
    dan engine berjalan penuh kecepatan.

Cara kerja (kompatibel dengan kode QThread lama):
    * Subkelas cukup mengganti basis ``QThread`` -> ``ProcWorker``. Sinyal
      (progress / finished_ok / failed / finished), ``start()``,
      ``isRunning()``, ``wait()``, ``terminate()`` dan ``cancel_flag.set()``
      tetap sama.
    * ``start()`` memotret atribut instance (payload) lalu menjalankan
      ``run()`` KELAS YANG SAMA di proses anak ('spawn') terhadap objek
      pengganti. Jalur perhitungan identik -> hasil numerik identik.
    * ``self.state`` (AppState/QObject) dipotret menjadi objek sederhana berisi
      cfg & profil (load, pv_norm, grid_status, datetimes, deg_status).
    * Emisi sinyal di anak dikirim lewat Queue; GUI membacanya dengan QTimer.
      Sinyal progress diteruskan langsung (hanya yang terbaru per tick);
      sinyal akhir (finished_ok/failed) ditahan sampai atribut balik
      (_SYNC_BACK, mis. 'errors', '_result_rows') diterapkan.
"""
from __future__ import annotations

import multiprocessing as mp
import queue as _queue
import threading
import traceback
from types import SimpleNamespace

from PySide6.QtCore import QObject, QTimer, Signal

_CTX = None


def _ctx():
    global _CTX
    if _CTX is None:
        _CTX = mp.get_context('spawn')      # sama di Windows / .exe / Linux
    return _CTX


# ------------------------------------------------------------- sisi anak
class _Emitter:
    def __init__(self, q, name, terminal):
        self._q, self._name, self._terminal = q, name, terminal

    def emit(self, *args):
        self._q.put(('sig', self._name, args, self._terminal))

    def connect(self, *_a, **_k):          # tak dipakai di anak
        pass


def _snapshot_state(st):
    """AppState (QObject) -> objek sederhana yang dapat di-pickle."""
    return SimpleNamespace(
        cfg=dict(getattr(st, 'cfg', {}) or {}),
        load=getattr(st, 'load', None),
        pv_norm=getattr(st, 'pv_norm', None),
        grid_status=getattr(st, 'grid_status', None),
        datetimes=getattr(st, 'datetimes', None),
        deg_status=getattr(st, 'deg_status', None),
    )


def _child_main(mod_name, cls_name, payload, sig_names, sync_back, lang,
                q, cancel_ev):
    """Titik masuk proses anak: jalankan cls.run() atas objek pengganti."""
    try:
        try:
            from ..config.i18n import set_language
        except Exception:                     # dipanggil sbg modul absolut
            from app.config.i18n import set_language
        set_language(lang or 'ID')
        import importlib
        mod = importlib.import_module(mod_name)
        cls = getattr(mod, cls_name)
        obj = SimpleNamespace(**payload)
        for name, terminal in sig_names:
            setattr(obj, name, _Emitter(q, name, terminal))
        obj.cancel_flag = cancel_ev
        obj.isInterruptionRequested = cancel_ev.is_set
        cls.run(obj)
        back = {k: getattr(obj, k) for k in sync_back if hasattr(obj, k)}
        q.put(('done', back))
    except BaseException:                      # pragma: no cover
        q.put(('sig', 'failed', (traceback.format_exc(),), True))
        q.put(('done', {}))
    finally:
        try:
            q.close()
            q.join_thread()                    # pastikan data terkirim penuh
        except Exception:
            pass


# ------------------------------------------------------------- sisi GUI
class _CancelFlag:
    """Pengganti threading.Event di sisi GUI; diteruskan ke anak saat start."""

    def __init__(self):
        self._local = threading.Event()
        self._mp = None

    def bind(self, ev):
        self._mp = ev
        if self._local.is_set():
            ev.set()

    def set(self):
        self._local.set()
        if self._mp is not None:
            try:
                self._mp.set()
            except Exception:
                pass

    def is_set(self):
        return self._local.is_set()

    def clear(self):
        self._local.clear()
        if self._mp is not None:
            try:
                self._mp.clear()
            except Exception:
                pass


class ProcWorker(QObject):
    """Basis pekerja latar berbasis proses (antarmuka mirip QThread)."""
    finished = Signal()
    # Sinyal akhir: ditahan sampai atribut balik diterapkan.
    _TERMINAL = ('finished_ok', 'failed')
    # Atribut yang dikirim balik dari anak ke objek GUI setelah run() selesai.
    _SYNC_BACK = ('errors', '_result_rows')
    POLL_MS = 30

    def __init__(self, *a, **k):
        super().__init__()
        self._proc = None
        self._q = None
        self._timer = None
        self._running = False
        self._pending = []
        self._launching = False
        self._launch_err = None

    # -- payload ---------------------------------------------------------
    def _payload(self):
        skip = {'_proc', '_q', '_timer', '_running', '_pending', '_launching',
                '_launch_err', 'cancel_flag'}
        out = {}
        for k, v in self.__dict__.items():
            if k in skip or type(v).__name__ == 'SignalInstance':
                continue
            if k == 'state' and hasattr(v, 'data_ready'):
                v = _snapshot_state(v)
            out[k] = v
        return out

    def _signal_names(self):
        names = []
        for klass in type(self).__mro__:
            if klass is ProcWorker or not issubclass(klass, ProcWorker):
                break
            for name, val in vars(klass).items():
                if isinstance(val, Signal) and name != 'finished' \
                        and name not in [n for n, _t in names]:
                    names.append((name, name in self._TERMINAL))
        return names

    # -- API mirip QThread ----------------------------------------------
    def start(self):
        if self._running:
            return
        from ..config.i18n import get_language
        ctx = _ctx()
        ev = ctx.Event()
        cf = self.__dict__.get('cancel_flag')
        if not isinstance(cf, _CancelFlag):
            new = _CancelFlag()
            if cf is not None and getattr(cf, 'is_set', lambda: False)():
                new.set()
            cf = new
            self.cancel_flag = cf
        cf.bind(ev)
        self._q = ctx.Queue()
        cls = type(self)
        self._proc = ctx.Process(
            target=_child_main,
            args=(cls.__module__, cls.__name__, self._payload(),
                  self._signal_names(), tuple(self._SYNC_BACK),
                  get_language(), self._q, ev),
            daemon=False)                      # anak boleh membuat pool
        self._pending = []
        self._running = True
        # Process.start() menulis payload (profil numpy) ke pipe dan MENUNGGU
        # anak selesai start (~0,3 dtk) -> dijalankan di thread pembantu agar
        # GUI tidak tertahan sedikit pun saat tombol Run ditekan.
        self._launching = True
        self._launch_err = None

        def _launch(proc=self._proc):
            try:
                proc.start()
            except Exception as e:            # pragma: no cover
                self._launch_err = str(e)
            finally:
                self._launching = False
        threading.Thread(target=_launch, daemon=True).start()
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def isRunning(self):
        return bool(self._running)

    def is_running(self):
        return self.isRunning()

    def requestInterruption(self):
        cf = self.__dict__.get('cancel_flag')
        if cf is not None:
            cf.set()

    def wait(self, msecs=None):
        """Tunggu selesai (dipakai saat menutup halaman/aplikasi)."""
        if not self._running:
            return True
        import time
        t_end = None if msecs is None else time.monotonic() + msecs / 1000.0
        while self._running:
            if getattr(self, '_launching', False):
                time.sleep(0.02)
            self._poll(block=True)
            if not self._running:
                break
            if t_end is not None and time.monotonic() >= t_end:
                return False
        return True

    def terminate(self):
        import time
        t_end = time.monotonic() + 5.0
        while getattr(self, '_launching', False) and time.monotonic() < t_end:
            time.sleep(0.02)                   # tunggu anak benar-benar mulai
        p = self._proc
        if p is not None and p.is_alive():
            try:
                p.terminate()
            except Exception:
                pass
        self._finish(emit=False)

    # -- penerimaan pesan -------------------------------------------------
    def _poll(self, block=False):
        q = self._q
        if q is None:
            return
        last_progress = {}
        try:
            while True:
                try:
                    msg = q.get(timeout=0.05) if block else q.get_nowait()
                except _queue.Empty:
                    break
                block = False
                kind = msg[0]
                if kind == 'sig':
                    _k, name, args, terminal = msg
                    if terminal:
                        self._pending.append((name, args))
                    else:
                        last_progress[name] = args
                elif kind == 'done':
                    for name, args in last_progress.items():
                        self._emit(name, args)
                    last_progress = {}
                    for k, v in (msg[1] or {}).items():
                        setattr(self, k, v)
                    pend, self._pending = self._pending, []
                    for name, args in pend:
                        self._emit(name, args)
                    self._finish(emit=True)
                    return
        except (EOFError, OSError):
            pass
        for name, args in last_progress.items():
            self._emit(name, args)
        if getattr(self, '_launching', False):
            return                             # anak belum selesai dijalankan
        if self._launch_err:
            err, self._launch_err = self._launch_err, None
            self._emit('failed', (err,))
            self._finish(emit=True)
            return
        p = self._proc
        if p is not None and not p.is_alive() and self._running:
            # anak mati tanpa pesan 'done' (mis. di-kill / crash)
            try:
                while True:
                    msg = q.get_nowait()
                    if msg[0] == 'done':
                        break
            except Exception:
                pass
            pend, self._pending = self._pending, []
            for name, args in pend:
                self._emit(name, args)
            if not pend and p.exitcode not in (0, None) \
                    and not self.cancel_flag.is_set():
                self._emit('failed', (f'Background process exited '
                                      f'(code {p.exitcode}).',))
            self._finish(emit=True)

    def _emit(self, name, args):
        sig = getattr(self, name, None)
        if sig is None:
            return
        try:
            sig.emit(*args)
        except RuntimeError:                   # penerima sudah dihapus
            pass

    def _finish(self, emit):
        if self._timer is not None:
            try:
                self._timer.stop()
            except RuntimeError:
                pass
        p, self._proc = self._proc, None
        if p is not None:
            try:
                p.join(timeout=2.0)
            except Exception:
                pass
        was = self._running
        self._running = False
        if self._q is not None:
            try:
                self._q.close()
            except Exception:
                pass
            self._q = None
        if emit and was:
            try:
                self.finished.emit()
            except RuntimeError:
                pass
