"""
@title 牌譜データ正規化 (proto3 省略フィールド補完)
@description protobuf の MessageToDict は proto3 のデフォルト値 (0 / False / 先頭 enum) を
             出力しないため、seat=0 や chang=0 (東場), ju=0 (1局) などのキーが牌譜 JSON から
             欠落する。シミュレーターや record_evaluator は seat 等の存在を前提にしているため、
             proto 定義 (descriptor) を参照して欠落したスカラー値を補完する。
"""

from majsoul_wrapper.proto import liqi_pb2 as pb
from google.protobuf.descriptor import FieldDescriptor

# Why: trim_game_record で意図的に削除したキーは補完すると実データと異なる値
#      (例: zhenting=False) が復活してしまうため、補完対象から除外する。
STRIP_KEYS = frozenset({'zhenting', 'paishan', 'passed', 'timeuse', 'timeAdd', 'timeFixed', 'views'})

_NUMERIC_TYPES = {
    FieldDescriptor.TYPE_DOUBLE, FieldDescriptor.TYPE_FLOAT,
    FieldDescriptor.TYPE_INT64, FieldDescriptor.TYPE_UINT64,
    FieldDescriptor.TYPE_INT32, FieldDescriptor.TYPE_UINT32,
    FieldDescriptor.TYPE_FIXED64, FieldDescriptor.TYPE_FIXED32,
    FieldDescriptor.TYPE_SFIXED32, FieldDescriptor.TYPE_SFIXED64,
    FieldDescriptor.TYPE_SINT32, FieldDescriptor.TYPE_SINT64,
}


def _fill_defaults(obj, descriptor):
    """descriptor に従い、dict に欠落しているスカラーフィールドのデフォルト値を補完する (破壊的)"""
    if not isinstance(obj, dict):
        return
    for field in descriptor.fields:
        key = field.json_name
        if key in STRIP_KEYS or field.name in STRIP_KEYS:
            continue
        is_repeated = field.label == FieldDescriptor.LABEL_REPEATED
        if field.type == FieldDescriptor.TYPE_MESSAGE:
            # Why: map フィールドや未設定のサブメッセージは補完しない (存在有無に意味があるため)
            if field.message_type.GetOptions().map_entry:
                continue
            value = obj.get(key)
            if is_repeated and isinstance(value, list):
                for item in value:
                    _fill_defaults(item, field.message_type)
            elif isinstance(value, dict):
                _fill_defaults(value, field.message_type)
            continue
        # Why: repeated (空リスト) や oneof / optional (presence あり) は補完すると
        #      「キーの存在」で判定しているロジックの意味が変わるため対象外。
        if is_repeated or field.containing_oneof is not None or key in obj:
            continue
        if field.type in _NUMERIC_TYPES:
            obj[key] = 0
        elif field.type == FieldDescriptor.TYPE_BOOL:
            obj[key] = False
        elif field.type == FieldDescriptor.TYPE_ENUM:
            obj[key] = field.enum_type.values_by_number[0].name if 0 in field.enum_type.values_by_number else 0


def _walk(obj):
    """{"class_name": X, "data": {...}} 形式の入れ子をすべて探して補完する"""
    if isinstance(obj, dict):
        class_name = obj.get('class_name')
        data = obj.get('data')
        if isinstance(class_name, str) and isinstance(data, dict):
            cls = getattr(pb, class_name, None)
            if cls is not None and hasattr(cls, 'DESCRIPTOR'):
                _fill_defaults(data, cls.DESCRIPTOR)
        for v in obj.values():
            _walk(v)
    elif isinstance(obj, list):
        for item in obj:
            _walk(item)


def normalize_record(record):
    """
    @title 牌譜 JSON の正規化
    @description save_game_record が出力する {head, detail_records, decoded_rounds} 形式の牌譜に対し、
                 欠落した proto3 デフォルト値 (seat=0 等) を補完して返す。入力 dict を直接変更する。
    @param {dict} record - 牌譜 JSON
    @returns {dict} 補完済みの牌譜 JSON (入力と同一オブジェクト)
    """
    if not isinstance(record, dict):
        return record
    head = record.get('head')
    if isinstance(head, dict):
        _fill_defaults(head, pb.RecordGame.DESCRIPTOR)
    detail = record.get('detail_records')
    if isinstance(detail, dict):
        _fill_defaults(detail, pb.GameDetailRecords.DESCRIPTOR)
    _walk(record)
    return record
