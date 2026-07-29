# Instrucciones del repositorio

- El repositorio canónico de publicación está en
  `C:\Users\Iago\Desktop\Arfoxia-Local-Ai-proyect-Spanish-`, rama `main`, con
  `origin` en GitHub. El árbol de trabajo puede estar en
  `C:\Users\Iago\Documents\Proyecto Glaceon`.
- Todo cambio funcional, visual, de configuración o de seguridad debe incluir
  una entrada clara en `CHANGELOG.md` dentro del mismo commit.
- Antes de publicar, ejecuta las pruebas proporcionales al cambio y comprueba
  que no se incluyen credenciales, datos locales, modelos ni dependencias
  generadas.
- Después de cada cambio solicitado, sincroniza únicamente los archivos
  publicables con el repositorio canónico, actualiza el changelog, crea un
  commit descriptivo y sube `main` a `origin`.
- Nunca copies los metadatos `.git` del árbol de trabajo ni el `.git` anidado de
  `mobile`; tampoco uses `push --force` para publicar.
