"""
Wait on multiple :class:`threading.Event` instances.

Based on code from: https://stackoverflow.com/questions/12317940/python-threading-can-i-sleep-on-two-threading-events-simultaneously/12320352#12320352
"""
import threading
from typing import Callable


def or_set(self) -> None:
    self._set()
    self.changed()


def or_clear(self) -> None:
    self._clear()
    self.changed()


def orify(event: threading.Event, changed_callback: Callable) -> None:
    """
    Override ``set`` and ``clear`` methods on event to call specified callback
    function after performing default behaviour.

    Parameters
    ----------
    event : threading.Event
        The event object to override.
    changed_callback : callable
        The callback function to be called after performing the default action.
    """
    event.changed = changed_callback
    if not hasattr(event, '_set'):
        # `set`/`clear` methods have not been overridden on event yet.
        # Override methods to call `changed_callback` after performing default
        # action.
        event._set = event.set
        event._clear = event.clear
        event.set = lambda: or_set(event)
        event.clear = lambda: or_clear(event)


def OrEvent(*events: threading.Event) -> threading.Event:
    """
    Parameters
    ----------
    events : list(threading.Event)
        List of events.

    Returns
    -------
    threading.Event
        Event that is set when **at least one** of the events in :data:`events`
        is set.
    """
    or_event = threading.Event()

    def changed() -> None:
        """
        Set ``or_event`` if any of the specified events have been set.
        """
        bools = [i_event.is_set() for i_event in events]
        if any(bools):
            or_event.set()
        else:
            or_event.clear()

    for event_i in events:
        # Override ``set`` and ``clear`` methods on event to update state of
        # `or_event` after performing default behaviour.
        orify(event_i, changed)

    # Set the initial state of `or_event`.
    changed()
    return or_event
