from hwIo.ioThread import IoThread
from typing import Optional

_synthThread: Optional[IoThread] = None


def initialize():
	global _synthThread
	if _synthThread:
		return
	_synthThread = IoThread()
	_synthThread.start()


def terminate():
	global _synthThread
	if not _synthThread:
		return
	_synthThread.stop()
	_synthThread = None