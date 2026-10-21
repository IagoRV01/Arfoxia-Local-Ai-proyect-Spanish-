#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../native/client_sessions.h"
static void packet(struct arfoxia_sessions *s,uint32_t seq,uint32_t session,unsigned mode) {
    char data[35];
    assert(snprintf(data,sizeof(data),"ARFOXIA10:%010u:%010u:%u\n",seq,session,mode)==34);
    arfoxia_session_step(s,data,34);
}
int main(void) {
    struct arfoxia_sessions s={0};
    packet(&s,1,1,1); assert(!s.active); /* Old file must not auto-start. */
    packet(&s,2,1,1); assert(!s.active); /* Same epoch still cannot start. */
    packet(&s,3,2,1); assert(s.active && s.mode==1 && s.lease==59);
    packet(&s,3,2,2); assert(s.mode==1 && s.lease==58); /* Replay. */
    packet(&s,4,1,0); assert(s.active && s.lease==57); /* Older epoch. */
    packet(&s,5,2,2); assert(s.mode==2 && s.lease==59);
    packet(&s,6,2,0); assert(!s.active);
    packet(&s,7,2,1); assert(!s.active); /* Stop cannot be undone by heartbeat. */
    packet(&s,8,3,3); assert(s.active && s.mode==3);
    for (unsigned i=0;i<59;++i) arfoxia_session_step(&s,NULL,0);
    assert(!s.active && !s.terminal);
    packet(&s,9,3,1); assert(!s.active); /* Nor after lease expiry. */
    packet(&s,10,4,1); assert(s.active);
    for (unsigned i=11;i<1810;++i) packet(&s,i,4,1);
    assert(!s.active && !s.terminal); /* Heartbeat cannot extend five minutes. */
    packet(&s,1810,5,1); assert(s.active);
    while (!s.terminal) packet(&s,s.sequence+1,s.session+1,1);
    assert(s.total==ARFOXIA_CLIENT_LIMIT && !s.active);
    packet(&s,99999,99999,1); assert(!s.active);
    s=(struct arfoxia_sessions){0};
    arfoxia_session_step(&s,"bad",3); assert(s.terminal && !s.active);
    s=(struct arfoxia_sessions){0}; packet(&s,1,1,0); packet(&s,2,2,1);
    packet(&s,3,1,4); assert(s.active && !s.terminal); /* Old owner cannot end new epoch. */
    packet(&s,4,2,0); assert(!s.active && !s.terminal);
    packet(&s,5,2,4); assert(s.terminal && !s.active); /* Finish even while hidden. */
    uint32_t seq=99,epoch=99; unsigned mode=99;
    assert(!arfoxia_parse_session("ARFOXIA10:4294967296:0000000001:1\n",34,&seq,&epoch,&mode));
    assert(!arfoxia_parse_session("ARFOXIA10:0000000001:0000000000:1\n",34,&seq,&epoch,&mode));
    assert(seq==99 && epoch==99 && mode==99);
    /* Repeated explicit starts/stops reuse the same bounded state. */
    for (unsigned cycle=0;cycle<10000;++cycle) {
        s=(struct arfoxia_sessions){0}; packet(&s,1,1,0);
        for (unsigned n=1;n<100;++n) {
            packet(&s,n*2,n+1,1); assert(s.active);
            packet(&s,n*2+1,n+1,0); assert(!s.active);
        }
    }
    puts("Repeatable sessions: baseline, replay, stop, expiry, restart, caps and invalid packets passed");
    return 0;
}
