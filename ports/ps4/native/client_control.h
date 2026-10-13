/* Owned ASCII control protocol and bounded motion; no Sony types or calls. */
#ifndef ARFOXIA_CLIENT_CONTROL_H
#define ARFOXIA_CLIENT_CONTROL_H
#include <stddef.h>
#include <stdint.h>

enum { ARFOXIA_STOP=0, ARFOXIA_WALK=1, ARFOXIA_SIT=2, ARFOXIA_IDLE=3 };
static inline int arfoxia_parse_control(const char *data, size_t size, uint32_t *sequence, unsigned *mode) {
    const char prefix[] = "ARFOXIA9:";
    if (!data || !sequence || !mode || size != 22) return 0;
    for (unsigned i=0; i<9; ++i) if (data[i] != prefix[i]) return 0;
    uint32_t value=0;
    for (unsigned i=9; i<19; ++i) {
        unsigned digit=(unsigned char)data[i]-'0';
        if (digit > 9 || value > (UINT32_MAX-digit)/10) return 0;
        value=value*10+digit;
    }
    if (!value || data[19] != ':' || data[20] < '0' || data[20] > '3' || data[21] != '\n') return 0;
    *sequence=value;
    *mode=(unsigned)(data[20]-'0');
    return 1;
}

struct arfoxia_motion { float x,y,vx,vy,min_x,max_x,min_y,max_y; };
static inline int arfoxia_motion_init(struct arfoxia_motion *value, float width, float height) {
    if (!value || !(width >= 320 && width <= 8192 && height >= 320 && height <= 8192)) return 0;
    value->min_x=32; value->max_x=width-192-32;
    value->max_y=height-240-32;
    value->min_y=value->max_y > 128 ? value->max_y-96 : 32;
    value->x=value->max_x; value->y=value->max_y;
    value->vx=-4; value->vy=-1;
    return 1;
}
static inline unsigned arfoxia_motion_step(struct arfoxia_motion *value, unsigned step, unsigned mode) {
    if (mode == ARFOXIA_SIT) return 8;
    if (mode != ARFOXIA_WALK) return 9;
    value->x+=value->vx; value->y+=value->vy;
    if (value->x <= value->min_x) { value->x=value->min_x; value->vx=4; }
    if (value->x >= value->max_x) { value->x=value->max_x; value->vx=-4; }
    if (value->y <= value->min_y) { value->y=value->min_y; value->vy=1; }
    if (value->y >= value->max_y) { value->y=value->max_y; value->vy=-1; }
    return (value->vx < 0 ? 4 : 0)+(step%4);
}
#endif
