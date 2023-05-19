
..
  We avoid using bigger heading types as readthedocs annoyingly collapses all table-of-contents
  otherwise, which is extremely annoying for small projects.
  (there's a mountain of empty vertical space on almost all projects! why collapse?)

.. testsetup :: *

   integration_data_path = Path('../tests/integration/data').resolve()

   blue_geotiff_path = integration_data_path / 'LC08_L1TP_090084_20160121_20170405_01_T1/LC08_L1TP_090084_20160121_20170405_01_T1_B2.TIF'

   tmp_path = Path(tempfile.mkdtemp())

   collection = tmp_path / 'collection'
   collection.mkdir()

.. testcleanup :: *

   import shutil
   shutil.rmtree(tmp_path)


EO3 Datasets
------------
