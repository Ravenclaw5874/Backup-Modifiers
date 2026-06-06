bl_info = {
    "name": "Backup Modifiers",
    "author": "R4V3N",
    "version": (1, 0, 2),
    "blender": (3, 0, 0),
    "location": "Properties > Modifiers",
    "description": "Apply modifiers with a backup. Easily switch to backup object",
    "category": "Object",
}

import bpy
import uuid

# 메타볼(META) 제외: 모디파이어를 지원하는 지오메트리만 남김.
VALID_TYPES = {'MESH', 'CURVE', 'FONT', 'SURFACE'}

# --- 유틸리티: UUID로 오브젝트 찾기 ---
def get_obj_by_uuid(uuid_str):
    if not uuid_str:
        return None
    for obj in bpy.data.objects:
        if obj.mod_backup_uuid == uuid_str:
            return obj
    return None

# --- 유틸리티: 콜렉션 스위칭 및 가시성 제어 ---
def swap_objects_and_collections(obj_to_hide, obj_to_show, context):
    backup_col = None
    for col in bpy.data.collections:
        if col.mod_backup_col_marker == "BACKUP_ORIGINALS":
            backup_col = col
            break
            
    if not backup_col:
        backup_col = bpy.data.collections.new("Backup_Originals")
        backup_col.mod_backup_col_marker = "BACKUP_ORIGINALS"
        context.scene.collection.children.link(backup_col)

    target_col = context.collection
    for col in obj_to_hide.users_collection:
        if col != backup_col:
            target_col = col
            break

    if obj_to_show.name not in target_col.objects:
        target_col.objects.link(obj_to_show)

    if backup_col and obj_to_show.name in backup_col.objects:
        backup_col.objects.unlink(obj_to_show)

    if backup_col and obj_to_hide.name not in backup_col.objects:
        backup_col.objects.link(obj_to_hide)

    for col in list(obj_to_hide.users_collection):
        if col != backup_col:
            col.objects.unlink(obj_to_hide)

    obj_to_hide.hide_viewport = True
    obj_to_hide.hide_render = True
    obj_to_show.hide_viewport = False
    obj_to_show.hide_render = False

    for obj in context.view_layer.objects:
        obj.select_set(False)
    obj_to_show.select_set(True)
    context.view_layer.objects.active = obj_to_show


# --- 오퍼레이터 1: Apply or Update Modifiers (Curve 변환 포함) ---
class OBJECT_OT_modifier_backup_apply(bpy.types.Operator):
    bl_idname = "object.modifier_backup_apply"
    bl_label = "Apply / Convert"
    bl_description = "Apply modifiers, or update an existing one"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type in VALID_TYPES

    def execute(self, context):
        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        current_obj = context.active_object

        if not current_obj.mod_backup_uuid:
            current_obj.mod_backup_uuid = uuid.uuid4().hex

        # 1. [업데이트 모드] 적용본(Mesh)이 이미 존재하는 경우
        if current_obj.mod_backup_applied_uuid:
            applied_obj = get_obj_by_uuid(current_obj.mod_backup_applied_uuid)
            
            if not applied_obj:
                current_obj.mod_backup_applied_uuid = "" 
            else:
                depsgraph = context.evaluated_depsgraph_get()
                eval_obj = current_obj.evaluated_get(depsgraph)
                new_mesh = bpy.data.meshes.new_from_object(
                    eval_obj, 
                    preserve_all_data_layers=True, 
                    depsgraph=depsgraph
                )

                old_mesh = applied_obj.data
                applied_obj.data = new_mesh
                
                if old_mesh and old_mesh.users == 0:
                    bpy.data.meshes.remove(old_mesh)
                
                applied_obj.matrix_world = current_obj.matrix_world.copy()
                swap_objects_and_collections(current_obj, applied_obj, context)
                self.report({'INFO'}, f"Updated Applied Mesh: {applied_obj.name}")
                return {'FINISHED'}

        # 2. [생성 모드] 처음 적용본을 만드는 경우
        if not current_obj.mod_backup_applied_uuid:
            
            if current_obj.type == 'MESH':
                depsgraph = context.evaluated_depsgraph_get()
                eval_obj = current_obj.evaluated_get(depsgraph)
                new_mesh = bpy.data.meshes.new_from_object(
                    eval_obj, 
                    preserve_all_data_layers=True, 
                    depsgraph=depsgraph
                )
                
                applied_obj = current_obj.copy()
                applied_obj.data = new_mesh
                applied_obj.modifiers.clear()
                
            else:
                applied_obj = current_obj.copy()
                applied_obj.data = current_obj.data.copy()
                
                target_col = context.collection
                for col in current_obj.users_collection:
                    if col.mod_backup_col_marker != "BACKUP_ORIGINALS":
                        target_col = col
                        break
                target_col.objects.link(applied_obj)
                
                for obj in context.view_layer.objects:
                    obj.select_set(False)
                applied_obj.select_set(True)
                context.view_layer.objects.active = applied_obj
                
                bpy.ops.object.convert(target='MESH')
            
            new_applied_uuid = uuid.uuid4().hex
            applied_obj.mod_backup_uuid = new_applied_uuid
            applied_obj.mod_backup_orig_uuid = current_obj.mod_backup_uuid
            applied_obj.mod_backup_applied_uuid = ""
            
            current_obj.mod_backup_applied_uuid = new_applied_uuid
            applied_obj.matrix_world = current_obj.matrix_world.copy()

            swap_objects_and_collections(current_obj, applied_obj, context)
            self.report({'INFO'}, f"Applied & Converted Node: {applied_obj.name}")
            return {'FINISHED'}

        return {'CANCELLED'}


# --- 오퍼레이터 2: Go to Original ---
class OBJECT_OT_modifier_backup_go_original(bpy.types.Operator):
    bl_idname = "object.modifier_backup_go_original"
    bl_label = "Go to Original"
    bl_description = "Go back to the original object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type in VALID_TYPES

    def execute(self, context):
        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        current_obj = context.active_object
        if not current_obj.mod_backup_orig_uuid:
            return {'CANCELLED'}

        orig_obj = get_obj_by_uuid(current_obj.mod_backup_orig_uuid)
        if orig_obj:
            orig_obj.matrix_world = current_obj.matrix_world.copy()
            swap_objects_and_collections(current_obj, orig_obj, context)
            self.report({'INFO'}, f"Switched to Original: {orig_obj.name}")
        else:
            self.report({'ERROR'}, "Original object not found (Maybe deleted?)")
        return {'FINISHED'}


# --- 오퍼레이터 3: Go to Applied ---
class OBJECT_OT_modifier_backup_go_applied(bpy.types.Operator):
    bl_idname = "object.modifier_backup_go_applied"
    bl_label = "Go to Applied"
    bl_description = "Switch to the applied object WITHOUT overwriting its mesh data"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type in VALID_TYPES

    def execute(self, context):
        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        current_obj = context.active_object
        if not current_obj.mod_backup_applied_uuid:
            return {'CANCELLED'}
            
        applied_obj = get_obj_by_uuid(current_obj.mod_backup_applied_uuid)
        if applied_obj:
            applied_obj.matrix_world = current_obj.matrix_world.copy()
            swap_objects_and_collections(current_obj, applied_obj, context)
            self.report({'INFO'}, f"Switched to Applied: {applied_obj.name}")
        else:
            self.report({'ERROR'}, "Applied object not found (Maybe deleted?)")
        return {'FINISHED'}


# --- 초경량 UI 패널 (1-Row Design) ---
class PROPERTIES_PT_modifier_backup(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'modifier'
    bl_label = ""
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        if not obj or obj.type not in VALID_TYPES:
            return

        has_orig = bool(obj.mod_backup_orig_uuid)
        has_applied = bool(obj.mod_backup_applied_uuid)
        has_modifiers = len(obj.modifiers) > 0

        # 모든 버튼을 한 줄(Row)에 배치
        row = layout.row(align=True)
        
        # 1. (왼쪽) Go to Original
        sub_orig = row.row(align=True)
        sub_orig.enabled = has_orig
        sub_orig.operator("object.modifier_backup_go_original", text="Original", icon='TRIA_LEFT')

        # 2. (중간) Go to Applied
        sub_app = row.row(align=True)
        sub_app.enabled = has_applied
        sub_app.operator("object.modifier_backup_go_applied", text="Applied", icon='TRIA_RIGHT')

        # 3. (오른쪽) Apply or Update
        sub_apply = row.row(align=True)
        if has_applied:
            sub_apply.operator("object.modifier_backup_apply", text="Update", icon='FILE_REFRESH')
        else:
            sub_apply.enabled = has_modifiers or obj.type != 'MESH'
            sub_apply.operator("object.modifier_backup_apply", text="Apply", icon='MODIFIER')


# --- 등록 (Registration) ---
classes = (
    OBJECT_OT_modifier_backup_apply,
    OBJECT_OT_modifier_backup_go_original,
    OBJECT_OT_modifier_backup_go_applied,
    PROPERTIES_PT_modifier_backup,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
        
    bpy.types.Object.mod_backup_uuid = bpy.props.StringProperty()
    bpy.types.Object.mod_backup_orig_uuid = bpy.props.StringProperty()
    bpy.types.Object.mod_backup_applied_uuid = bpy.props.StringProperty()
    bpy.types.Collection.mod_backup_col_marker = bpy.props.StringProperty()

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
        
    del bpy.types.Object.mod_backup_uuid
    del bpy.types.Object.mod_backup_orig_uuid
    del bpy.types.Object.mod_backup_applied_uuid
    del bpy.types.Collection.mod_backup_col_marker

if __name__ == "__main__":
    register()