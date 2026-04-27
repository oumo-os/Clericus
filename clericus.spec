# clericus.spec
# PyInstaller build spec for Clericus desktop app.
# Usage:
#   pip install pyinstaller
#   pyinstaller clericus.spec
#
# Output: dist/Clericus/  (folder) or dist/Clericus.exe (Windows one-file)
# The --onedir mode is preferred for faster startup with large ML libraries.

import sys
from pathlib import Path

ROOT = Path(spec_path).parent   # noqa: F821 — set by PyInstaller

block_cipher = None

a = Analysis(
    [str(ROOT / 'app.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Ship the entire gui/ folder (static HTML + API server)
        (str(ROOT / 'gui'),         'gui'),
        # Ship export templates
        (str(ROOT / 'export' / 'templates'), 'export/templates'),
        # Ship the sentence-transformers default cache so the model
        # is bundled rather than downloaded on first run.
        # (Uncomment and adjust path after running the app once to warm the cache.)
        # (str(Path.home() / '.cache' / 'torch' / 'sentence_transformers'),
        #  'sentence_transformers_cache'),
    ],
    hiddenimports=[
        # FastAPI / uvicorn
        'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
        'uvicorn.protocols', 'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # Clericus modules (ensure all pipeline modules are collected)
        'contemplation.document_planner', 'contemplation.plan_and_discover',
        'drafting.recursive_drafter', 'drafting.draft_section',
        'drafting.review_section', 'review.review_pipeline',
        'sourceprep.index', 'sourceprep.ingest', 'sourceprep.chunker',
        'sourceprep.chunker_embed', 'sourceprep.metadata',
        'template.analyze_template', 'template.structure_generator',
        'discovery.discovery', 'retrieval.retriever',
        'internal_kb', 'established_facts', 'question_tracker',
        'curated_kb', 'export.exporters',
        'utils.app_config', 'utils.vector_store', 'utils.config',
        'utils.text_tools', 'utils.references', 'utils.logging',
        'llm_client.call_llm',
        # ML deps
        'faiss', 'sentence_transformers', 'numpy',
        # Optional backends (bundled but only active if user configures them)
        'anthropic', 'openai', 'google.genai',
        # pywebview backends
        'webview', 'webview.platforms',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude things we definitely don't need to keep bundle size down
        'tkinter', 'matplotlib', 'PIL', 'cv2', 'torch',
        'tensorflow', 'keras', 'sklearn',
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)   # noqa: F821

exe = EXE(   # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Clericus',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # no terminal window
    disable_windowed_traceback=False,
    # icon='gui/static/icon.ico',   # uncomment once icon is added
)

coll = COLLECT(   # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Clericus',
)
