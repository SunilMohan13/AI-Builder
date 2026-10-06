"""Place-name resolution for the Punjab-Haryana-Delhi NCR corridor.

A question like "what is the air quality in Delhi" has to become coordinates
before any store can answer it. This is a small committed gazetteer rather
than a geocoding service: the AOI is fixed, the set of places people ask
about is small, and an offline lookup keeps the copilot's tool layer
deterministic and testable.

An unknown place resolves to ``None`` and the caller must say so. Guessing a
location is how a confident answer about the wrong city gets produced.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from aeropulse_geospatial.grid import in_default_aoi, to_grid_id


@dataclass(frozen=True)
class Place:
    """A resolvable location inside the AOI.

    Attributes:
        name: Canonical display name.
        lat: Latitude in degrees.
        lon: Longitude in degrees.
        state: Indian state or union territory.
        aliases: Alternative spellings and former names.
        radius_km: Sensible query radius for a place of this size.
    """

    name: str
    lat: float
    lon: float
    state: str
    aliases: tuple[str, ...] = ()
    radius_km: float = 25.0

    @property
    def grid_id(self) -> str:
        """H3 res-8 cell containing this place's centre."""
        return to_grid_id(self.lat, self.lon)

    @property
    def in_aoi(self) -> bool:
        """Whether this place lies inside the monitored corridor."""
        return in_default_aoi(self.lat, self.lon)


#: Cities, districts and NCR towns the corridor actually covers. Coordinates
#: are city centres. Aliases cover common spellings, the older names people
#: still use, and the CPCB station naming people copy out of bulletins.
PLACES: tuple[Place, ...] = (
    Place(
        "Delhi",
        28.6139,
        77.2090,
        "Delhi",
        aliases=("new delhi", "ncr", "delhi ncr", "national capital region", "dilli"),
        radius_km=40.0,
    ),
    Place("Anand Vihar", 28.6469, 77.3159, "Delhi", aliases=("anand vihar delhi",), radius_km=10.0),
    Place("Rohini", 28.7495, 77.0565, "Delhi", radius_km=10.0),
    Place("Dwarka", 28.5921, 77.0460, "Delhi", radius_km=10.0),
    Place("Gurugram", 28.4595, 77.0266, "Haryana", aliases=("gurgaon",), radius_km=20.0),
    Place("Noida", 28.5355, 77.3910, "Uttar Pradesh", radius_km=20.0),
    Place("Ghaziabad", 28.6692, 77.4538, "Uttar Pradesh", radius_km=20.0),
    Place("Faridabad", 28.4089, 77.3178, "Haryana", radius_km=20.0),
    Place("Greater Noida", 28.4744, 77.5040, "Uttar Pradesh", radius_km=20.0),
    Place("Sonipat", 28.9931, 77.0151, "Haryana", aliases=("sonepat",), radius_km=20.0),
    Place("Panipat", 29.3909, 76.9635, "Haryana", radius_km=20.0),
    Place("Karnal", 29.6857, 76.9905, "Haryana", radius_km=20.0),
    Place("Kurukshetra", 29.9695, 76.8783, "Haryana", radius_km=20.0),
    Place("Ambala", 30.3752, 76.7821, "Haryana", radius_km=20.0),
    Place("Hisar", 29.1492, 75.7217, "Haryana", aliases=("hissar",), radius_km=25.0),
    Place("Rohtak", 28.8955, 76.6066, "Haryana", radius_km=20.0),
    Place("Chandigarh", 30.7333, 76.7794, "Chandigarh", radius_km=20.0),
    Place("Ludhiana", 30.9010, 75.8573, "Punjab", radius_km=25.0),
    Place("Amritsar", 31.6340, 74.8723, "Punjab", radius_km=25.0),
    Place("Jalandhar", 31.3260, 75.5762, "Punjab", aliases=("jullundur",), radius_km=25.0),
    Place("Patiala", 30.3398, 76.3869, "Punjab", radius_km=25.0),
    Place("Bathinda", 30.2110, 74.9455, "Punjab", aliases=("bhatinda",), radius_km=25.0),
    Place("Sangrur", 30.2458, 75.8421, "Punjab", radius_km=25.0),
    Place("Moga", 30.8165, 75.1717, "Punjab", radius_km=25.0),
    Place("Firozpur", 30.9331, 74.6225, "Punjab", aliases=("ferozepur",), radius_km=25.0),
    Place("Barnala", 30.3782, 75.5462, "Punjab", radius_km=25.0),
    Place("Muktsar", 30.4745, 74.5161, "Punjab", aliases=("sri muktsar sahib",), radius_km=25.0),
)


def _normalise(text: str) -> str:
    """Casefold, strip accents, and collapse punctuation for matching."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9 ]+", " ", stripped.casefold()).strip()


def _index() -> dict[str, Place]:
    table: dict[str, Place] = {}
    for place in PLACES:
        table[_normalise(place.name)] = place
        for alias in place.aliases:
            table[_normalise(alias)] = place
    return table


_LOOKUP = _index()


def resolve_place(text: str) -> Place | None:
    """Resolve a free-text place name to a known location.

    Matching is exact on the normalised name first, then a whole-word search
    so "air quality in Delhi right now" still resolves. Substring matching is
    deliberately word-bounded: without it "Moga" matches inside "Mogadishu".

    Args:
        text: A place name, or a phrase containing one.

    Returns:
        The matching :class:`Place`, or None when nothing matches. Callers
        must surface the None rather than falling back to a default city.
    """
    if not text or not text.strip():
        return None
    needle = _normalise(text)
    if not needle:
        return None

    direct = _LOOKUP.get(needle)
    if direct is not None:
        return direct

    # Longest key first, so "greater noida" wins over "noida".
    for key in sorted(_LOOKUP, key=len, reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", needle):
            return _LOOKUP[key]
    return None


def known_places() -> list[str]:
    """Return every canonical place name, for prompts and error messages."""
    return [place.name for place in PLACES]
