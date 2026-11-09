import {
  ClientSideRowModelApiModule,
  ClientSideRowModelModule,
  CsvExportModule,
  ModuleRegistry,
  RowApiModule,
  RowSelectionModule,
  TextFilterModule,
} from "ag-grid-community";
import {
  LicenseManager,
  SetFilterModule,
} from "ag-grid-enterprise";

ModuleRegistry.registerModules([
  ClientSideRowModelModule,
  ClientSideRowModelApiModule,
  CsvExportModule,
  RowApiModule,
  RowSelectionModule,
  TextFilterModule,
  SetFilterModule,
]);

const licenseKey = process.env.NEXT_PUBLIC_AG_GRID_LICENSE_KEY;
if (licenseKey) {
  LicenseManager.setLicenseKey(licenseKey);
}
