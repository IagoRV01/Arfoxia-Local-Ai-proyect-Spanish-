/* Bounded repeatable sessions, pure C: no SDK, filesystem or UI calls. */
#ifndef ARFOXIA_CLIENT_SESSIONS_H
#define ARFOXIA_CLIENT_SESSIONS_H
#include "client_control.h"
#define ARFOXIA_SESSION_LEASE 60u
#define ARFOXIA_SESSION_LIMIT 1800u
#define ARFOXIA_CLIENT_LIMIT 5400u
#define ARFOXIA_SESSION_FINISH 4u
struct arfoxia_sessions {
    uint32_t sequence, session;
    unsigned initialized, active, mode, lease, age, total, terminal;
};
static inline int arfoxia_decimal10(const char *text, uint32_t *output) {
    uint32_t value=0;
    for (unsigned i=0;i<10;++i) {
        unsigned digit=(unsigned char)text[i]-'0';
        if (digit>9 || value>(UINT32_MAX-digit)/10) return 0;
        value=value*10+digit;
    }
    if (!value) return 0;
    *output=value; return 1;
}
static inline int arfoxia_parse_session(const char *data, size_t size,
                                      uint32_t *sequence, uint32_t *session, unsigned *mode) {
    const char prefix[]="ARFOXIA10:";
    uint32_t seq,epoch;
    if (!data || !sequence || !session || !mode || size!=34) return 0;
    for (unsigned i=0;i<10;++i) if (data[i]!=prefix[i]) return 0;
    if (data[20]!=':' || data[31]!=':' || data[32]<'0' || data[32]>'4' || data[33]!='\n' ||
        !arfoxia_decimal10(data+10,&seq) || !arfoxia_decimal10(data+21,&epoch)) return 0;
    *sequence=seq; *session=epoch; *mode=(unsigned)(data[32]-'0'); return 1;
}
static inline void arfoxia_session_hide(struct arfoxia_sessions *s) {
    s->active=0; s->mode=ARFOXIA_STOP; s->lease=0;
}
/* Call exactly once per worker slot. A first valid packet establishes a
 * baseline, NEVER starts rendering. Expired/stopped epochs cannot resume.
 * Invalid input is terminal; a missing file merely stops renewing the lease.
 */
static inline void arfoxia_session_step(struct arfoxia_sessions *s, const char *data, size_t size) {
    if (s->terminal) return;
    if (++s->total>=ARFOXIA_CLIENT_LIMIT) { s->terminal=1; arfoxia_session_hide(s); return; }
    if (data) {
        uint32_t sequence,session; unsigned mode;
        if (!arfoxia_parse_session(data,size,&sequence,&session,&mode)) {
            s->terminal=1; arfoxia_session_hide(s); return;
        }
        if (!s->initialized) {
            s->initialized=1; s->sequence=sequence; s->session=session;
            if (mode==ARFOXIA_SESSION_FINISH) s->terminal=1;
            arfoxia_session_hide(s); return;
        }
        if (sequence>s->sequence) {
            s->sequence=sequence;
            if (session>=s->session && mode==ARFOXIA_SESSION_FINISH) {
                s->terminal=1; arfoxia_session_hide(s); return;
            }
            if (session>s->session) {
                s->session=session; s->age=0;
                s->active=mode!=ARFOXIA_STOP;
                if (!s->active) arfoxia_session_hide(s);
            }
            if (session==s->session && s->active) {
                if (mode==ARFOXIA_STOP) arfoxia_session_hide(s);
                else { s->mode=mode; s->lease=ARFOXIA_SESSION_LEASE; }
            }
        }
    }
    if (s->active && (++s->age>=ARFOXIA_SESSION_LIMIT || !s->lease || --s->lease==0))
        arfoxia_session_hide(s);
}
#endif
