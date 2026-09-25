"""Small, explicit owner commands; never infer posture from model/web text."""
import re
import unicodedata


def posture_command(text: str) -> str | None:
    folded = ''.join(c for c in unicodedata.normalize('NFD', text.casefold())
                     if not unicodedata.combining(c))
    folded = ' '.join(folded.split()).strip(' .!¡,')
    folded = re.sub(r'^arfoxia[, ]+', '', folded)
    folded = re.sub(r'^por favor[, ]+', '', folded)
    folded = re.sub(r'[, ]+por favor$', '', folded)
    if re.fullmatch(
        r'(?:sientate|quedate sentado|permanece sentado|sit down|stay seated)'
        r'(?: (?:mientras juego(?: a .+)?|sin dormir|sin dormirte|while i play)){0,2}',
        folded,
    ):
        return 'sit'
    if re.fullmatch(r'(?:vuelve a pasear|puedes volver a pasear|levantate|deja de estar sentado|resume wandering)', folded):
        return 'resume'
    return None
