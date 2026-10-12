#include <assert.h>
#include <stdio.h>
#include "../native/dispatch_contract.h"
int main(void) {
    const char *guid = "01234567-89AB-CDEF-0123-456789ABCDEF";
    assert(arfoxia_guid_equal(guid, guid));
    assert(arfoxia_guid_equal("01234567-89ab-cdef-0123-456789abcdef", guid));
    assert(!arfoxia_guid_equal(NULL, guid));
    assert(!arfoxia_guid_equal(guid, NULL));
    assert(!arfoxia_guid_equal("", guid));
    assert(!arfoxia_guid_equal("01234567-89AB-CDEF-0123-456789ABCDE", guid));
    assert(!arfoxia_guid_equal("01234567-89AB-CDEF-0123-456789ABCDEF1", guid));
    assert(!arfoxia_guid_equal("01234567_89AB-CDEF-0123-456789ABCDEF", guid));
    assert(!arfoxia_guid_equal("G1234567-89AB-CDEF-0123-456789ABCDEF", guid));
    assert(!arfoxia_guid_equal("11234567-89AB-CDEF-0123-456789ABCDEF", guid));
    puts("dispatch profile GUID guards: 10 cases passed");
    return 0;
}
