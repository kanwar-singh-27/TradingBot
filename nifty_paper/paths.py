"""Canonical paper books and explicit handling of older journal paths."""

from pathlib import Path


SOURCE_OUTPUTS = {'public': Path('runtime/public'), 'public_loose': Path('runtime/public-loose'),
                  'demo': Path('runtime/validation-demo')}


def existing_outputs(root, source):
    root = Path(root).resolve()
    if source not in SOURCE_OUTPUTS:
        raise ValueError('Unsupported paper source')
    paths = [root / SOURCE_OUTPUTS[source], root / 'runtime' / source]
    return list(dict.fromkeys(path for path in paths if (path / 'paper.sqlite3').exists()))


def resolve_output(root, source, explicit=None):
    if explicit is not None:
        return Path(explicit).resolve()
    existing = existing_outputs(root, source)
    if len(existing) > 1:
        raise ValueError('Multiple existing journals for '+source+'; choose --output explicitly: '+', '.join(str(p) for p in existing))
    return existing[0] if existing else Path(root).resolve() / SOURCE_OUTPUTS[source]