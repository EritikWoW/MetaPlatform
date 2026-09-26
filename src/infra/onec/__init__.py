from .importer import OneCConfigImporter
from .model import MPXConfig, MPXObject
from .onec_requisites_parser import (
    OneCXmlParser,
    OneCMetaObject,
    OneCRequisite,
    OneCTabularPart,
    OneCTabularColumn,
    OneCEnumValue,
    parse_object_xml,
    enrich_manifest_payload,
)
from .source_compat import (
    ResolvedOneCSource,
    detect_onec_source_kind,
    find_xmlconf_root,
    inspect_1cd_header,
    inspect_dt_header,
    resolve_onec_source,
)
from .onecd_source import (
    OneCDConfigSource,
    collect_onecd_metadata_catalog,
)
from .physical_schema import (
    SOURCE_SNAPSHOT_ASSET_KEY,
    build_onec_compatibility_snapshot,
    discover_related_onec_sources,
    inspect_1cd_database,
    inspect_dt_dump,
    store_source_snapshot_asset,
    summarize_xmlconf_root,
)
from .storage_alignment import (
    STORAGE_ALIGNMENT_ASSET_KEY,
    build_storage_alignment_report,
    build_storage_alignment_report_from_snapshot,
    get_meta_platform_storage_profile,
    store_storage_alignment_asset,
)
from .source_structure_compare import build_source_structure_compare_report
from .physical_mapping import (
    PHYSICAL_MAPPING_ASSET_KEY,
    build_physical_mapping_report,
    build_physical_mapping_report_from_catalogs,
    collect_xmlconf_object_catalog,
    inspect_1cd_table_catalog,
    store_physical_mapping_asset,
)
from .metadata_structure import (
    apply_onec_structural_metadata,
    build_metadata_structure,
    build_storage_profile,
    storage_family_for_obj_type,
)
from .data_migration import (
    ONECD_DATA_MIGRATION_ASSET_KEY,
    migrate_onecd_data_to_mpdb,
    sanitize_column_name,
    sanitize_table_name,
)
from .com_data_audit import (
    ONEC_COM_DATA_AUDIT_ASSET_KEY,
    build_com_data_audit,
    store_com_data_audit_asset,
)
