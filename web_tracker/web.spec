# -*- mode: python ; coding: utf-8 -*-

import sys
sys.setrecursionlimit(2000)

block_cipher = None

SETUP_DIR = r'D:/code/pysot'
a = Analysis(['web_service.py'],
             pathex=['D:/code/pysot'],
             binaries=[],
             datas=[(SETUP_DIR+'/web_tracker/templates', 'templates'),(SETUP_DIR+'/web_tracker/siamrpn_r50_l234_dwxcorr_otb', 'siamrpn_r50_l234_dwxcorr_otb')],

             hiddenimports=[
                               'numpy',
                               'torch',
                               'opencv-python',
                               'yacs',
                               'tqdm',
                               'pyyaml',
                               'matplotlib',
                               'colorama',
                               'cython',
                               'tensorboardX',
                               'flask'
                          ],
             hookspath=[],
             hooksconfig={},
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)

exe = EXE(pyz,
          a.scripts, 
          [],
          exclude_binaries=True,
          name='web_service',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=True,
          disable_windowed_traceback=False,
          target_arch=None,
          codesign_identity=None,
          entitlements_file=None )
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas, 
               strip=False,
               upx=True,
               upx_exclude=[],
               name='web_service')
