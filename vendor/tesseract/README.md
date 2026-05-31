# Portable Tesseract

Place a portable Tesseract runtime here when packaging the app:

```text
vendor/tesseract/
  tesseract.exe
  tessdata/
    eng.traineddata
    chi_sim.traineddata
```

The app searches this directory before user settings, system installs, and PATH.
