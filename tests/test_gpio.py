import sys
from importlib import reload
from types import ModuleType

from boiler_relay import gpio


def load_gpio(monkeypatch, bbio):
  with monkeypatch.context() as patch:
    if bbio is None:
      patch.setitem(sys.modules, "Adafruit_BBIO", None)
      patch.setitem(sys.modules, "Adafruit_BBIO.GPIO", None)
    else:
      package = ModuleType("Adafruit_BBIO")
      package.GPIO = bbio
      patch.setitem(sys.modules, "Adafruit_BBIO", package)
      patch.setitem(sys.modules, "Adafruit_BBIO.GPIO", bbio)
    return reload(gpio).GPIO


def test_uses_adafruit_bbio_when_installed(monkeypatch):
  bbio = ModuleType("Adafruit_BBIO.GPIO")

  try:
    assert load_gpio(monkeypatch, bbio) is bbio
  finally:
    reload(gpio)


def test_falls_back_to_the_stub_when_not_installed(monkeypatch, capsys):
  try:
    stub = load_gpio(monkeypatch, None)

    assert stub.__name__ == "GPIO"
    assert not isinstance(stub, ModuleType)
    assert "using stub GPIO" in capsys.readouterr().out
  finally:
    reload(gpio)


def test_stub_reads_inputs_as_low(monkeypatch):
  try:
    stub = load_gpio(monkeypatch, None)

    assert stub.input("P8_7") == stub.LOW
  finally:
    reload(gpio)
