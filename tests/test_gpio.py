import logging
import sys
from types import ModuleType

import pytest

from boiler_relay.gpio import GPIOLoader, StubGPIO


class Forbidden:
  @staticmethod
  def find_spec(name, path=None, target=None):
    if name.split(".")[0] == "Adafruit_BBIO":
      raise AssertionError(f"{name} was imported")


def install_bbio(monkeypatch, bbio):
  if bbio is None:
    monkeypatch.setitem(sys.modules, "Adafruit_BBIO", None)
    monkeypatch.setitem(sys.modules, "Adafruit_BBIO.GPIO", None)
  else:
    package = ModuleType("Adafruit_BBIO")
    package.GPIO = bbio
    monkeypatch.setitem(sys.modules, "Adafruit_BBIO", package)
    monkeypatch.setitem(sys.modules, "Adafruit_BBIO.GPIO", bbio)


def forbid_bbio(monkeypatch):
  monkeypatch.delitem(sys.modules, "Adafruit_BBIO", raising=False)
  monkeypatch.delitem(sys.modules, "Adafruit_BBIO.GPIO", raising=False)
  monkeypatch.setattr(sys, "meta_path", [Forbidden] + sys.meta_path)


def test_uses_adafruit_bbio_when_installed(monkeypatch):
  bbio = ModuleType("Adafruit_BBIO.GPIO")
  install_bbio(monkeypatch, bbio)

  assert GPIOLoader().load() is bbio


def test_falls_back_to_the_stub_when_not_installed(monkeypatch, caplog):
  install_bbio(monkeypatch, None)

  with caplog.at_level(logging.WARNING, logger="boiler_relay.gpio"):
    loaded = GPIOLoader().load()

  assert loaded is StubGPIO
  assert "using stub GPIO" in caplog.text


def test_stub_reads_inputs_as_low(monkeypatch):
  install_bbio(monkeypatch, None)

  assert GPIOLoader().input("P8_7") == StubGPIO.LOW


def test_nothing_is_imported_until_the_gpio_is_used(monkeypatch):
  forbid_bbio(monkeypatch)

  GPIOLoader()


def test_the_loader_passes_attributes_through_to_the_backend(monkeypatch):
  bbio = ModuleType("Adafruit_BBIO.GPIO")
  bbio.OUT = 7
  install_bbio(monkeypatch, bbio)

  assert GPIOLoader().OUT == 7


def test_the_stub_is_used_without_importing_the_real_gpio(monkeypatch):
  forbid_bbio(monkeypatch)
  loader = GPIOLoader()

  loader.use_stub()
  loader.setup("P8_10", loader.OUT)
  loader.output("P8_10", loader.HIGH)

  assert loader.load() is StubGPIO


def test_the_stub_cannot_replace_a_real_gpio_already_loaded(monkeypatch):
  install_bbio(monkeypatch, ModuleType("Adafruit_BBIO.GPIO"))
  loader = GPIOLoader()
  loader.load()

  with pytest.raises(RuntimeError, match="already loaded"):
    loader.use_stub()
