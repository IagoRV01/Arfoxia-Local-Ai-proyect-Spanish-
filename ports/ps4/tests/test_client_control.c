#include <assert.h>
#include <string.h>
#include <stdio.h>
#include "../native/client_control.h"

int main(void) {
    uint32_t sequence=99; unsigned mode=99;
    assert(arfoxia_parse_control("ARFOXIA9:0000000001:1\n",22,&sequence,&mode));
    assert(sequence == 1 && mode == ARFOXIA_WALK);
    assert(arfoxia_parse_control("ARFOXIA9:4294967295:0\n",22,&sequence,&mode));
    assert(sequence == UINT32_MAX && mode == ARFOXIA_STOP);
    const char *invalid[]={"ARFOXIA9:0000000000:1\n","ARFOXIA9:4294967296:1\n",
        "ARFOXIA9:0000000001:4\n","ARFOXIA9:-000000001:1\n","ARFOXIA9:0000000001:1 ",
        "ARFOXIA8:0000000001:1\n","ARFOXIA9:00000000x1:1\n"};
    for (unsigned i=0; i<sizeof(invalid)/sizeof(*invalid); ++i)
        assert(!arfoxia_parse_control(invalid[i],strlen(invalid[i]),&sequence,&mode));
    assert(!arfoxia_parse_control(NULL,22,&sequence,&mode));
    assert(!arfoxia_parse_control("ARFOXIA9:0000000001:1\n",21,&sequence,&mode));
    struct arfoxia_motion motion;
    assert(!arfoxia_motion_init(&motion,319,1080));
    assert(!arfoxia_motion_init(&motion,1920,9000));
    const float dimensions[][2]={{320,320},{1920,1080},{8192,8192}};
    for (unsigned d=0; d<3; ++d) {
        assert(arfoxia_motion_init(&motion,dimensions[d][0],dimensions[d][1]));
        float initial_x=motion.x,initial_y=motion.y;
        assert(arfoxia_motion_step(&motion,0,ARFOXIA_SIT) == 8);
        assert(arfoxia_motion_step(&motion,0,ARFOXIA_IDLE) == 9);
        assert(motion.x == initial_x && motion.y == initial_y);
        for (unsigned i=0; i<100000; ++i) {
            assert(arfoxia_motion_step(&motion,i,ARFOXIA_WALK) < 8);
            assert(motion.x >= motion.min_x && motion.x <= motion.max_x);
            assert(motion.y >= motion.min_y && motion.y <= motion.max_y);
        }
    }
    puts("Client control: strict protocol and 300000 bounded motion steps passed");
    return 0;
}
