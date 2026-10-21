"""Explicit, repeatable menu-session controls. No payload, autoload or game hooks."""
import argparse
import ftplib
import io
import ipaddress
import queue
import threading
import time

if __package__:
    from .lease_control import MODES as BASE_MODES, REMOTE
    from .probe_transport import read_bounded
else:
    from lease_control import MODES as BASE_MODES, REMOTE
    from probe_transport import read_bounded

CONTROL = 'control-v10.txt'
MODES = dict(BASE_MODES, finish=4)
TEMP = 'control-v10.upload-verify'
LOG = 'dispatch-v10.txt'
LOAD_LOG = 'dispatch-load-v10.txt'


def encode(sequence, session, mode):
    for value in (sequence, session):
        if type(value) is not int or not 1 <= value <= 4294967295:
            raise ValueError('Sequence/session out of range')
    if type(mode) is not int or mode not in MODES.values():
        raise ValueError('Unknown pet mode')
    return f'ARFOXIA10:{sequence:010d}:{session:010d}:{mode}\n'.encode('ascii')


def decode(value):
    if (len(value) != 34 or value[:10] != b'ARFOXIA10:' or value[20:21] != b':' or
            value[31:32] != b':' or value[-1:] != b'\n' or not value[10:20].isdigit() or
            not value[21:31].isdigit() or value[32:33] not in (b'0', b'1', b'2', b'3', b'4')):
        raise ValueError('Invalid existing control file; preserve it')
    result = int(value[10:20]), int(value[21:31]), int(value[32:33])
    if encode(*result) != value:
        raise ValueError('Invalid control encoding')
    return result


def client_ready(ftp):
    log = read_bounded(ftp, LOG, 65536).decode('ascii', errors='strict')
    if ('CLIENT_CONTROL_BASELINE 1\n' not in log or
            any(marker in log for marker in ('CLIENT_PROCESS_FINISHED', 'PREVIEW_CLEANED',
                'CLIENT_SCENE_CHANGED_STOP', 'FRAME_NOT_ON_UI_HALTED', 'FRAME_POST_FAILED_HALTED',
                'MANAGED_EXCEPTION', 'PHASE_QUEUE_CLEANUP'))):
        raise ValueError('PS4 trial is not ready or has finished; no automatic reload')
    return log


def wait_started(ftp, session, *, clock=time.monotonic, pause=time.sleep):
    # A historical log is not a liveness check. Require an acknowledgement for
    # this NEW epoch, not merely FTP success or an old module-start marker.
    signed = session if session < 2147483648 else session - 4294967296
    marker = f'CLIENT_SESSION_STARTED {signed}'
    deadline = clock() + 4
    while clock() < deadline:
        if marker in client_ready(ftp).splitlines():
            return
        pause(0.15)
    raise ValueError('No acknowledgement for the new PS4 session; no heartbeat will be sent')


def write_control(host, mode, *, session=None, start=False, prepare=False, ftp_factory=ftplib.FTP):
    """A new epoch requires start=True. Updates must name their owned epoch.

    prepare=True writes STOP before a separately guarded one-shot trial load;
    it cannot activate a sprite. Nothing in this module loads native code.
    """
    address = ipaddress.ip_address(host)
    if not address.is_private or address.is_unspecified or address.is_multicast:
        raise ValueError('An explicit private owner-console IP is required')
    if mode not in MODES or (start and prepare) or (prepare and (mode != 'stop' or session is not None)):
        raise ValueError('Invalid action')
    if not (start or prepare) and (type(session) is not int or not 1 <= session <= 4294967295):
        raise ValueError('An explicit owned session is required')
    if start and (mode in ('stop', 'finish') or session is not None):
        raise ValueError('Start requires a visible mode and no existing session')
    with ftp_factory(timeout=4) as ftp:
        ftp.connect(str(address), 2121)
        ftp.login()
        ftp.cwd(REMOTE)
        names = {name.rsplit('/', 1)[-1] for name in ftp.nlst()}
        if TEMP in names:
            raise ValueError('Interrupted control write; preserve temporary file')
        if prepare:
            if CONTROL in names or LOG in names or LOAD_LOG in names:
                raise ValueError('Trial already prepared or attempted; preserve files')
            previous, epoch = 0, 1
        else:
            if CONTROL not in names:
                raise ValueError('Missing prepared owner control file')
            previous, epoch, _ = decode(read_bounded(ftp, CONTROL, 35))
            client_ready(ftp)
            if start:
                epoch += 1
            elif session != epoch:
                raise ValueError('Another session replaced this controller; no overwrite')
        value = encode(previous + 1, epoch, MODES[mode])
        ftp.storbinary('STOR ' + TEMP, io.BytesIO(value))
        if read_bounded(ftp, TEMP, 35) != value:
            raise ValueError('Control byte verification failed')
        ftp.rename(TEMP, CONTROL)
        if start:
            wait_started(ftp, epoch)
        return previous + 1, epoch


def panel(host):
    import tkinter as tk
    from tkinter import ttk
    window = tk.Tk()
    window.title('Arfoxia · Sesiones PS4 (prueba de menú)')
    window.geometry('510x325')
    commands, messages = queue.Queue(), queue.Queue()
    closed = threading.Event()
    status = tk.StringVar(value='Sin iniciar. Requiere cliente v10 ya cargado y PS4 en el menú.')
    ttk.Label(window, text='Solo menú de PS4 · sin juegos ni autoarranque',
              font=('Segoe UI', 11, 'bold')).pack(pady=12)
    ttk.Button(window, text='Mostrar / Iniciar nueva sesión',
               command=lambda: commands.put(('start', 'walk'))).pack(pady=5)
    row = ttk.Frame(window)
    row.pack(pady=6)
    for label, mode in [('Caminar', 'walk'), ('Sentarse', 'sit'), ('Quieta', 'idle'), ('Retirar', 'stop')]:
        ttk.Button(row, text=label, command=lambda v=mode: commands.put(('mode', v))).pack(side='left', padx=3)
    ttk.Button(window, text='Finalizar prueba / Liberar recursos',
               command=lambda: commands.put(('mode', 'finish'))).pack(pady=5)
    ttk.Label(window, textvariable=status, wraplength=475).pack(pady=10)
    ttk.Label(window, text='Cada sesión: 5 min. Cliente: ~15 min desde la carga.\n'
              'Sin señal: se oculta en ~10 s. Retirar permite otra sesión explícita.').pack()

    def worker():
        session, owned_session, mode, next_beat, session_deadline = None, None, 'stop', 0.0, 0.0
        while not closed.is_set():
            try:
                action, selected = commands.get(timeout=0.15)
            except queue.Empty:
                action, selected = None, mode
            if closed.is_set():
                break
            if session is not None and time.monotonic() >= session_deadline and action != 'start':
                action, selected = 'mode', 'stop'
            try:
                if action == 'start':
                    _, session = write_control(host, selected, start=True)
                    owned_session = session
                    mode, next_beat = selected, time.monotonic() + 2
                    session_deadline = time.monotonic() + 300
                    messages.put(f'Sesión {session} aceptada por el cliente; no confirma dibujo en el televisor.')
                elif action == 'mode' and selected == 'finish' and owned_session is not None:
                    write_control(host, 'finish', session=owned_session)
                    session = owned_session = None
                    messages.put('Finalización solicitada. Hace falta una carga nueva para otra prueba.')
                elif action == 'mode' and session is None:
                    messages.put('Pulsa Mostrar para iniciar una nueva sesión; no se inicia sola.')
                elif session is not None and (action == 'mode' or time.monotonic() >= next_beat):
                    write_control(host, selected, session=session)
                    mode, next_beat = selected, time.monotonic() + 2
                    messages.put(f'Orden enviada: {mode} · sesión {session} (no confirma dibujo).')
                    if mode == 'stop':
                        session = None
            except (OSError, ValueError, EOFError, UnicodeError, ftplib.Error) as exc:
                session = None
                messages.put(f'Control detenido: {exc}. Sin reintento automático; pulsa Mostrar cuando esté listo.')
        if owned_session is not None:
            try:
                write_control(host, 'finish', session=owned_session)
            except (OSError, ValueError, EOFError, UnicodeError, ftplib.Error):
                pass  # Native lease expiry is the fallback, never a payload retry.

    def poll():
        while True:
            try:
                status.set(messages.get_nowait())
            except queue.Empty:
                break
        if not closed.is_set():
            window.after(150, poll)

    def close():
        closed.set()
        window.destroy()

    window.protocol('WM_DELETE_WINDOW', close)
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    poll()
    window.mainloop()
    thread.join(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--panel', action='store_true')
    parser.add_argument('--mode', choices=MODES, default='walk')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--start', action='store_true')
    group.add_argument('--session', type=int)
    args = parser.parse_args()
    if args.panel:
        panel(args.host)
    else:
        print('Requested control:', write_control(args.host, args.mode, session=args.session, start=args.start))


if __name__ == '__main__':
    main()
