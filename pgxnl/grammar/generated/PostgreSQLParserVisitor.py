# Generated from PostgreSQLParser.g4 (antlr/grammars-v4 sql/postgresql, MIT) by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .PostgreSQLParser import PostgreSQLParser
else:
    from PostgreSQLParser import PostgreSQLParser

# This class defines a complete generic visitor for a parse tree produced by PostgreSQLParser.

class PostgreSQLParserVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by PostgreSQLParser#root.
    def visitRoot(self, ctx:PostgreSQLParser.RootContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#stmtblock.
    def visitStmtblock(self, ctx:PostgreSQLParser.StmtblockContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#stmtmulti.
    def visitStmtmulti(self, ctx:PostgreSQLParser.StmtmultiContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#stmt.
    def visitStmt(self, ctx:PostgreSQLParser.StmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#callstmt.
    def visitCallstmt(self, ctx:PostgreSQLParser.CallstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createrolestmt.
    def visitCreaterolestmt(self, ctx:PostgreSQLParser.CreaterolestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#with_.
    def visitWith_(self, ctx:PostgreSQLParser.With_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#optrolelist.
    def visitOptrolelist(self, ctx:PostgreSQLParser.OptrolelistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alteroptrolelist.
    def visitAlteroptrolelist(self, ctx:PostgreSQLParser.AlteroptrolelistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alteroptroleelem.
    def visitAlteroptroleelem(self, ctx:PostgreSQLParser.AlteroptroleelemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createoptroleelem.
    def visitCreateoptroleelem(self, ctx:PostgreSQLParser.CreateoptroleelemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createuserstmt.
    def visitCreateuserstmt(self, ctx:PostgreSQLParser.CreateuserstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterrolestmt.
    def visitAlterrolestmt(self, ctx:PostgreSQLParser.AlterrolestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#in_database_.
    def visitIn_database_(self, ctx:PostgreSQLParser.In_database_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterrolesetstmt.
    def visitAlterrolesetstmt(self, ctx:PostgreSQLParser.AlterrolesetstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#droprolestmt.
    def visitDroprolestmt(self, ctx:PostgreSQLParser.DroprolestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#creategroupstmt.
    def visitCreategroupstmt(self, ctx:PostgreSQLParser.CreategroupstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#altergroupstmt.
    def visitAltergroupstmt(self, ctx:PostgreSQLParser.AltergroupstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#add_drop.
    def visitAdd_drop(self, ctx:PostgreSQLParser.Add_dropContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createschemastmt.
    def visitCreateschemastmt(self, ctx:PostgreSQLParser.CreateschemastmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#optschemaname.
    def visitOptschemaname(self, ctx:PostgreSQLParser.OptschemanameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#optschemaeltlist.
    def visitOptschemaeltlist(self, ctx:PostgreSQLParser.OptschemaeltlistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#schema_stmt.
    def visitSchema_stmt(self, ctx:PostgreSQLParser.Schema_stmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#variablesetstmt.
    def visitVariablesetstmt(self, ctx:PostgreSQLParser.VariablesetstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#set_rest.
    def visitSet_rest(self, ctx:PostgreSQLParser.Set_restContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#generic_set.
    def visitGeneric_set(self, ctx:PostgreSQLParser.Generic_setContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#set_rest_more.
    def visitSet_rest_more(self, ctx:PostgreSQLParser.Set_rest_moreContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#var_name.
    def visitVar_name(self, ctx:PostgreSQLParser.Var_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#var_list.
    def visitVar_list(self, ctx:PostgreSQLParser.Var_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#var_value.
    def visitVar_value(self, ctx:PostgreSQLParser.Var_valueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#iso_level.
    def visitIso_level(self, ctx:PostgreSQLParser.Iso_levelContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#boolean_or_string_.
    def visitBoolean_or_string_(self, ctx:PostgreSQLParser.Boolean_or_string_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#zone_value.
    def visitZone_value(self, ctx:PostgreSQLParser.Zone_valueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#encoding_.
    def visitEncoding_(self, ctx:PostgreSQLParser.Encoding_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#nonreservedword_or_sconst.
    def visitNonreservedword_or_sconst(self, ctx:PostgreSQLParser.Nonreservedword_or_sconstContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#variableresetstmt.
    def visitVariableresetstmt(self, ctx:PostgreSQLParser.VariableresetstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#reset_rest.
    def visitReset_rest(self, ctx:PostgreSQLParser.Reset_restContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#generic_reset.
    def visitGeneric_reset(self, ctx:PostgreSQLParser.Generic_resetContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#setresetclause.
    def visitSetresetclause(self, ctx:PostgreSQLParser.SetresetclauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#functionsetresetclause.
    def visitFunctionsetresetclause(self, ctx:PostgreSQLParser.FunctionsetresetclauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#variableshowstmt.
    def visitVariableshowstmt(self, ctx:PostgreSQLParser.VariableshowstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#constraintssetstmt.
    def visitConstraintssetstmt(self, ctx:PostgreSQLParser.ConstraintssetstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#constraints_set_list.
    def visitConstraints_set_list(self, ctx:PostgreSQLParser.Constraints_set_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#constraints_set_mode.
    def visitConstraints_set_mode(self, ctx:PostgreSQLParser.Constraints_set_modeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#checkpointstmt.
    def visitCheckpointstmt(self, ctx:PostgreSQLParser.CheckpointstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#discardstmt.
    def visitDiscardstmt(self, ctx:PostgreSQLParser.DiscardstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#altertablestmt.
    def visitAltertablestmt(self, ctx:PostgreSQLParser.AltertablestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alter_table_cmds.
    def visitAlter_table_cmds(self, ctx:PostgreSQLParser.Alter_table_cmdsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#partition_cmd.
    def visitPartition_cmd(self, ctx:PostgreSQLParser.Partition_cmdContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#index_partition_cmd.
    def visitIndex_partition_cmd(self, ctx:PostgreSQLParser.Index_partition_cmdContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alter_table_cmd.
    def visitAlter_table_cmd(self, ctx:PostgreSQLParser.Alter_table_cmdContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alter_column_default.
    def visitAlter_column_default(self, ctx:PostgreSQLParser.Alter_column_defaultContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#drop_behavior_.
    def visitDrop_behavior_(self, ctx:PostgreSQLParser.Drop_behavior_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#collate_clause_.
    def visitCollate_clause_(self, ctx:PostgreSQLParser.Collate_clause_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alter_using.
    def visitAlter_using(self, ctx:PostgreSQLParser.Alter_usingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#replica_identity.
    def visitReplica_identity(self, ctx:PostgreSQLParser.Replica_identityContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#reloptions.
    def visitReloptions(self, ctx:PostgreSQLParser.ReloptionsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#reloptions_.
    def visitReloptions_(self, ctx:PostgreSQLParser.Reloptions_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#reloption_list.
    def visitReloption_list(self, ctx:PostgreSQLParser.Reloption_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#reloption_elem.
    def visitReloption_elem(self, ctx:PostgreSQLParser.Reloption_elemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alter_identity_column_option_list.
    def visitAlter_identity_column_option_list(self, ctx:PostgreSQLParser.Alter_identity_column_option_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alter_identity_column_option.
    def visitAlter_identity_column_option(self, ctx:PostgreSQLParser.Alter_identity_column_optionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#partitionboundspec.
    def visitPartitionboundspec(self, ctx:PostgreSQLParser.PartitionboundspecContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#hash_partbound_elem.
    def visitHash_partbound_elem(self, ctx:PostgreSQLParser.Hash_partbound_elemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#hash_partbound.
    def visitHash_partbound(self, ctx:PostgreSQLParser.Hash_partboundContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#altercompositetypestmt.
    def visitAltercompositetypestmt(self, ctx:PostgreSQLParser.AltercompositetypestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alter_type_cmds.
    def visitAlter_type_cmds(self, ctx:PostgreSQLParser.Alter_type_cmdsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alter_type_cmd.
    def visitAlter_type_cmd(self, ctx:PostgreSQLParser.Alter_type_cmdContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#closeportalstmt.
    def visitCloseportalstmt(self, ctx:PostgreSQLParser.CloseportalstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#copystmt.
    def visitCopystmt(self, ctx:PostgreSQLParser.CopystmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#copy_from.
    def visitCopy_from(self, ctx:PostgreSQLParser.Copy_fromContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#program_.
    def visitProgram_(self, ctx:PostgreSQLParser.Program_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#copy_file_name.
    def visitCopy_file_name(self, ctx:PostgreSQLParser.Copy_file_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#copy_options.
    def visitCopy_options(self, ctx:PostgreSQLParser.Copy_optionsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#copy_opt_list.
    def visitCopy_opt_list(self, ctx:PostgreSQLParser.Copy_opt_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#copy_opt_item.
    def visitCopy_opt_item(self, ctx:PostgreSQLParser.Copy_opt_itemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#binary_.
    def visitBinary_(self, ctx:PostgreSQLParser.Binary_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#copy_delimiter.
    def visitCopy_delimiter(self, ctx:PostgreSQLParser.Copy_delimiterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#using_.
    def visitUsing_(self, ctx:PostgreSQLParser.Using_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#copy_generic_opt_list.
    def visitCopy_generic_opt_list(self, ctx:PostgreSQLParser.Copy_generic_opt_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#copy_generic_opt_elem.
    def visitCopy_generic_opt_elem(self, ctx:PostgreSQLParser.Copy_generic_opt_elemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#copy_generic_opt_arg.
    def visitCopy_generic_opt_arg(self, ctx:PostgreSQLParser.Copy_generic_opt_argContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#copy_generic_opt_arg_list.
    def visitCopy_generic_opt_arg_list(self, ctx:PostgreSQLParser.Copy_generic_opt_arg_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#copy_generic_opt_arg_list_item.
    def visitCopy_generic_opt_arg_list_item(self, ctx:PostgreSQLParser.Copy_generic_opt_arg_list_itemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createstmt.
    def visitCreatestmt(self, ctx:PostgreSQLParser.CreatestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#opttemp.
    def visitOpttemp(self, ctx:PostgreSQLParser.OpttempContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#opttableelementlist.
    def visitOpttableelementlist(self, ctx:PostgreSQLParser.OpttableelementlistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#opttypedtableelementlist.
    def visitOpttypedtableelementlist(self, ctx:PostgreSQLParser.OpttypedtableelementlistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#tableelementlist.
    def visitTableelementlist(self, ctx:PostgreSQLParser.TableelementlistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#typedtableelementlist.
    def visitTypedtableelementlist(self, ctx:PostgreSQLParser.TypedtableelementlistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#tableelement.
    def visitTableelement(self, ctx:PostgreSQLParser.TableelementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#typedtableelement.
    def visitTypedtableelement(self, ctx:PostgreSQLParser.TypedtableelementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#columnDef.
    def visitColumnDef(self, ctx:PostgreSQLParser.ColumnDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#columnOptions.
    def visitColumnOptions(self, ctx:PostgreSQLParser.ColumnOptionsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#colquallist.
    def visitColquallist(self, ctx:PostgreSQLParser.ColquallistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#colconstraint.
    def visitColconstraint(self, ctx:PostgreSQLParser.ColconstraintContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#colconstraintelem.
    def visitColconstraintelem(self, ctx:PostgreSQLParser.ColconstraintelemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#generated_when.
    def visitGenerated_when(self, ctx:PostgreSQLParser.Generated_whenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#constraintattr.
    def visitConstraintattr(self, ctx:PostgreSQLParser.ConstraintattrContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#tablelikeclause.
    def visitTablelikeclause(self, ctx:PostgreSQLParser.TablelikeclauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#tablelikeoptionlist.
    def visitTablelikeoptionlist(self, ctx:PostgreSQLParser.TablelikeoptionlistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#tablelikeoption.
    def visitTablelikeoption(self, ctx:PostgreSQLParser.TablelikeoptionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#tableconstraint.
    def visitTableconstraint(self, ctx:PostgreSQLParser.TableconstraintContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#constraintelem.
    def visitConstraintelem(self, ctx:PostgreSQLParser.ConstraintelemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#no_inherit_.
    def visitNo_inherit_(self, ctx:PostgreSQLParser.No_inherit_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#column_list_.
    def visitColumn_list_(self, ctx:PostgreSQLParser.Column_list_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#columnlist.
    def visitColumnlist(self, ctx:PostgreSQLParser.ColumnlistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#columnElem.
    def visitColumnElem(self, ctx:PostgreSQLParser.ColumnElemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#c_include_.
    def visitC_include_(self, ctx:PostgreSQLParser.C_include_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#key_match.
    def visitKey_match(self, ctx:PostgreSQLParser.Key_matchContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#exclusionconstraintlist.
    def visitExclusionconstraintlist(self, ctx:PostgreSQLParser.ExclusionconstraintlistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#exclusionconstraintelem.
    def visitExclusionconstraintelem(self, ctx:PostgreSQLParser.ExclusionconstraintelemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#exclusionwhereclause.
    def visitExclusionwhereclause(self, ctx:PostgreSQLParser.ExclusionwhereclauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#key_actions.
    def visitKey_actions(self, ctx:PostgreSQLParser.Key_actionsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#key_update.
    def visitKey_update(self, ctx:PostgreSQLParser.Key_updateContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#key_delete.
    def visitKey_delete(self, ctx:PostgreSQLParser.Key_deleteContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#key_action.
    def visitKey_action(self, ctx:PostgreSQLParser.Key_actionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#optinherit.
    def visitOptinherit(self, ctx:PostgreSQLParser.OptinheritContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#optpartitionspec.
    def visitOptpartitionspec(self, ctx:PostgreSQLParser.OptpartitionspecContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#partitionspec.
    def visitPartitionspec(self, ctx:PostgreSQLParser.PartitionspecContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#part_params.
    def visitPart_params(self, ctx:PostgreSQLParser.Part_paramsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#part_elem.
    def visitPart_elem(self, ctx:PostgreSQLParser.Part_elemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#table_access_method_clause.
    def visitTable_access_method_clause(self, ctx:PostgreSQLParser.Table_access_method_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#optwith.
    def visitOptwith(self, ctx:PostgreSQLParser.OptwithContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#oncommitoption.
    def visitOncommitoption(self, ctx:PostgreSQLParser.OncommitoptionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#opttablespace.
    def visitOpttablespace(self, ctx:PostgreSQLParser.OpttablespaceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#optconstablespace.
    def visitOptconstablespace(self, ctx:PostgreSQLParser.OptconstablespaceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#existingindex.
    def visitExistingindex(self, ctx:PostgreSQLParser.ExistingindexContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createstatsstmt.
    def visitCreatestatsstmt(self, ctx:PostgreSQLParser.CreatestatsstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterstatsstmt.
    def visitAlterstatsstmt(self, ctx:PostgreSQLParser.AlterstatsstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createasstmt.
    def visitCreateasstmt(self, ctx:PostgreSQLParser.CreateasstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#create_as_target.
    def visitCreate_as_target(self, ctx:PostgreSQLParser.Create_as_targetContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#with_data_.
    def visitWith_data_(self, ctx:PostgreSQLParser.With_data_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#creatematviewstmt.
    def visitCreatematviewstmt(self, ctx:PostgreSQLParser.CreatematviewstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#create_mv_target.
    def visitCreate_mv_target(self, ctx:PostgreSQLParser.Create_mv_targetContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#optnolog.
    def visitOptnolog(self, ctx:PostgreSQLParser.OptnologContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#refreshmatviewstmt.
    def visitRefreshmatviewstmt(self, ctx:PostgreSQLParser.RefreshmatviewstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createseqstmt.
    def visitCreateseqstmt(self, ctx:PostgreSQLParser.CreateseqstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterseqstmt.
    def visitAlterseqstmt(self, ctx:PostgreSQLParser.AlterseqstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#optseqoptlist.
    def visitOptseqoptlist(self, ctx:PostgreSQLParser.OptseqoptlistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#optparenthesizedseqoptlist.
    def visitOptparenthesizedseqoptlist(self, ctx:PostgreSQLParser.OptparenthesizedseqoptlistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#seqoptlist.
    def visitSeqoptlist(self, ctx:PostgreSQLParser.SeqoptlistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#seqoptelem.
    def visitSeqoptelem(self, ctx:PostgreSQLParser.SeqoptelemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#by_.
    def visitBy_(self, ctx:PostgreSQLParser.By_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#numericonly.
    def visitNumericonly(self, ctx:PostgreSQLParser.NumericonlyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#numericonly_list.
    def visitNumericonly_list(self, ctx:PostgreSQLParser.Numericonly_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createplangstmt.
    def visitCreateplangstmt(self, ctx:PostgreSQLParser.CreateplangstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#trusted_.
    def visitTrusted_(self, ctx:PostgreSQLParser.Trusted_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#handler_name.
    def visitHandler_name(self, ctx:PostgreSQLParser.Handler_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#inline_handler_.
    def visitInline_handler_(self, ctx:PostgreSQLParser.Inline_handler_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#validator_clause.
    def visitValidator_clause(self, ctx:PostgreSQLParser.Validator_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#validator_.
    def visitValidator_(self, ctx:PostgreSQLParser.Validator_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#procedural_.
    def visitProcedural_(self, ctx:PostgreSQLParser.Procedural_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createtablespacestmt.
    def visitCreatetablespacestmt(self, ctx:PostgreSQLParser.CreatetablespacestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#opttablespaceowner.
    def visitOpttablespaceowner(self, ctx:PostgreSQLParser.OpttablespaceownerContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#droptablespacestmt.
    def visitDroptablespacestmt(self, ctx:PostgreSQLParser.DroptablespacestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createextensionstmt.
    def visitCreateextensionstmt(self, ctx:PostgreSQLParser.CreateextensionstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#create_extension_opt_list.
    def visitCreate_extension_opt_list(self, ctx:PostgreSQLParser.Create_extension_opt_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#create_extension_opt_item.
    def visitCreate_extension_opt_item(self, ctx:PostgreSQLParser.Create_extension_opt_itemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterextensionstmt.
    def visitAlterextensionstmt(self, ctx:PostgreSQLParser.AlterextensionstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alter_extension_opt_list.
    def visitAlter_extension_opt_list(self, ctx:PostgreSQLParser.Alter_extension_opt_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alter_extension_opt_item.
    def visitAlter_extension_opt_item(self, ctx:PostgreSQLParser.Alter_extension_opt_itemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterextensioncontentsstmt.
    def visitAlterextensioncontentsstmt(self, ctx:PostgreSQLParser.AlterextensioncontentsstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createfdwstmt.
    def visitCreatefdwstmt(self, ctx:PostgreSQLParser.CreatefdwstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#fdw_option.
    def visitFdw_option(self, ctx:PostgreSQLParser.Fdw_optionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#fdw_options.
    def visitFdw_options(self, ctx:PostgreSQLParser.Fdw_optionsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#fdw_options_.
    def visitFdw_options_(self, ctx:PostgreSQLParser.Fdw_options_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterfdwstmt.
    def visitAlterfdwstmt(self, ctx:PostgreSQLParser.AlterfdwstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#create_generic_options.
    def visitCreate_generic_options(self, ctx:PostgreSQLParser.Create_generic_optionsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#generic_option_list.
    def visitGeneric_option_list(self, ctx:PostgreSQLParser.Generic_option_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alter_generic_options.
    def visitAlter_generic_options(self, ctx:PostgreSQLParser.Alter_generic_optionsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alter_generic_option_list.
    def visitAlter_generic_option_list(self, ctx:PostgreSQLParser.Alter_generic_option_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alter_generic_option_elem.
    def visitAlter_generic_option_elem(self, ctx:PostgreSQLParser.Alter_generic_option_elemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#generic_option_elem.
    def visitGeneric_option_elem(self, ctx:PostgreSQLParser.Generic_option_elemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#generic_option_name.
    def visitGeneric_option_name(self, ctx:PostgreSQLParser.Generic_option_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#generic_option_arg.
    def visitGeneric_option_arg(self, ctx:PostgreSQLParser.Generic_option_argContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createforeignserverstmt.
    def visitCreateforeignserverstmt(self, ctx:PostgreSQLParser.CreateforeignserverstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#type_.
    def visitType_(self, ctx:PostgreSQLParser.Type_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#foreign_server_version.
    def visitForeign_server_version(self, ctx:PostgreSQLParser.Foreign_server_versionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#foreign_server_version_.
    def visitForeign_server_version_(self, ctx:PostgreSQLParser.Foreign_server_version_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterforeignserverstmt.
    def visitAlterforeignserverstmt(self, ctx:PostgreSQLParser.AlterforeignserverstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createforeigntablestmt.
    def visitCreateforeigntablestmt(self, ctx:PostgreSQLParser.CreateforeigntablestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#importforeignschemastmt.
    def visitImportforeignschemastmt(self, ctx:PostgreSQLParser.ImportforeignschemastmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#import_qualification_type.
    def visitImport_qualification_type(self, ctx:PostgreSQLParser.Import_qualification_typeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#import_qualification.
    def visitImport_qualification(self, ctx:PostgreSQLParser.Import_qualificationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createusermappingstmt.
    def visitCreateusermappingstmt(self, ctx:PostgreSQLParser.CreateusermappingstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#auth_ident.
    def visitAuth_ident(self, ctx:PostgreSQLParser.Auth_identContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#dropusermappingstmt.
    def visitDropusermappingstmt(self, ctx:PostgreSQLParser.DropusermappingstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterusermappingstmt.
    def visitAlterusermappingstmt(self, ctx:PostgreSQLParser.AlterusermappingstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createpolicystmt.
    def visitCreatepolicystmt(self, ctx:PostgreSQLParser.CreatepolicystmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterpolicystmt.
    def visitAlterpolicystmt(self, ctx:PostgreSQLParser.AlterpolicystmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#rowsecurityoptionalexpr.
    def visitRowsecurityoptionalexpr(self, ctx:PostgreSQLParser.RowsecurityoptionalexprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#rowsecurityoptionalwithcheck.
    def visitRowsecurityoptionalwithcheck(self, ctx:PostgreSQLParser.RowsecurityoptionalwithcheckContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#rowsecuritydefaulttorole.
    def visitRowsecuritydefaulttorole(self, ctx:PostgreSQLParser.RowsecuritydefaulttoroleContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#rowsecurityoptionaltorole.
    def visitRowsecurityoptionaltorole(self, ctx:PostgreSQLParser.RowsecurityoptionaltoroleContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#rowsecuritydefaultpermissive.
    def visitRowsecuritydefaultpermissive(self, ctx:PostgreSQLParser.RowsecuritydefaultpermissiveContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#rowsecuritydefaultforcmd.
    def visitRowsecuritydefaultforcmd(self, ctx:PostgreSQLParser.RowsecuritydefaultforcmdContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#row_security_cmd.
    def visitRow_security_cmd(self, ctx:PostgreSQLParser.Row_security_cmdContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createamstmt.
    def visitCreateamstmt(self, ctx:PostgreSQLParser.CreateamstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#am_type.
    def visitAm_type(self, ctx:PostgreSQLParser.Am_typeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createtrigstmt.
    def visitCreatetrigstmt(self, ctx:PostgreSQLParser.CreatetrigstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#triggeractiontime.
    def visitTriggeractiontime(self, ctx:PostgreSQLParser.TriggeractiontimeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#triggerevents.
    def visitTriggerevents(self, ctx:PostgreSQLParser.TriggereventsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#triggeroneevent.
    def visitTriggeroneevent(self, ctx:PostgreSQLParser.TriggeroneeventContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#triggerreferencing.
    def visitTriggerreferencing(self, ctx:PostgreSQLParser.TriggerreferencingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#triggertransitions.
    def visitTriggertransitions(self, ctx:PostgreSQLParser.TriggertransitionsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#triggertransition.
    def visitTriggertransition(self, ctx:PostgreSQLParser.TriggertransitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#transitionoldornew.
    def visitTransitionoldornew(self, ctx:PostgreSQLParser.TransitionoldornewContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#transitionrowortable.
    def visitTransitionrowortable(self, ctx:PostgreSQLParser.TransitionrowortableContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#transitionrelname.
    def visitTransitionrelname(self, ctx:PostgreSQLParser.TransitionrelnameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#triggerforspec.
    def visitTriggerforspec(self, ctx:PostgreSQLParser.TriggerforspecContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#triggerforopteach.
    def visitTriggerforopteach(self, ctx:PostgreSQLParser.TriggerforopteachContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#triggerfortype.
    def visitTriggerfortype(self, ctx:PostgreSQLParser.TriggerfortypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#triggerwhen.
    def visitTriggerwhen(self, ctx:PostgreSQLParser.TriggerwhenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#function_or_procedure.
    def visitFunction_or_procedure(self, ctx:PostgreSQLParser.Function_or_procedureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#triggerfuncargs.
    def visitTriggerfuncargs(self, ctx:PostgreSQLParser.TriggerfuncargsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#triggerfuncarg.
    def visitTriggerfuncarg(self, ctx:PostgreSQLParser.TriggerfuncargContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#optconstrfromtable.
    def visitOptconstrfromtable(self, ctx:PostgreSQLParser.OptconstrfromtableContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#constraintattributespec.
    def visitConstraintattributespec(self, ctx:PostgreSQLParser.ConstraintattributespecContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#constraintattributeElem.
    def visitConstraintattributeElem(self, ctx:PostgreSQLParser.ConstraintattributeElemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createeventtrigstmt.
    def visitCreateeventtrigstmt(self, ctx:PostgreSQLParser.CreateeventtrigstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#event_trigger_when_list.
    def visitEvent_trigger_when_list(self, ctx:PostgreSQLParser.Event_trigger_when_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#event_trigger_when_item.
    def visitEvent_trigger_when_item(self, ctx:PostgreSQLParser.Event_trigger_when_itemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#event_trigger_value_list.
    def visitEvent_trigger_value_list(self, ctx:PostgreSQLParser.Event_trigger_value_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#altereventtrigstmt.
    def visitAltereventtrigstmt(self, ctx:PostgreSQLParser.AltereventtrigstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#enable_trigger.
    def visitEnable_trigger(self, ctx:PostgreSQLParser.Enable_triggerContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createassertionstmt.
    def visitCreateassertionstmt(self, ctx:PostgreSQLParser.CreateassertionstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#definestmt.
    def visitDefinestmt(self, ctx:PostgreSQLParser.DefinestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#definition.
    def visitDefinition(self, ctx:PostgreSQLParser.DefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#def_list.
    def visitDef_list(self, ctx:PostgreSQLParser.Def_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#def_elem.
    def visitDef_elem(self, ctx:PostgreSQLParser.Def_elemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#def_arg.
    def visitDef_arg(self, ctx:PostgreSQLParser.Def_argContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#old_aggr_definition.
    def visitOld_aggr_definition(self, ctx:PostgreSQLParser.Old_aggr_definitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#old_aggr_list.
    def visitOld_aggr_list(self, ctx:PostgreSQLParser.Old_aggr_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#old_aggr_elem.
    def visitOld_aggr_elem(self, ctx:PostgreSQLParser.Old_aggr_elemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#enum_val_list_.
    def visitEnum_val_list_(self, ctx:PostgreSQLParser.Enum_val_list_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#enum_val_list.
    def visitEnum_val_list(self, ctx:PostgreSQLParser.Enum_val_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterenumstmt.
    def visitAlterenumstmt(self, ctx:PostgreSQLParser.AlterenumstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#if_not_exists_.
    def visitIf_not_exists_(self, ctx:PostgreSQLParser.If_not_exists_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createopclassstmt.
    def visitCreateopclassstmt(self, ctx:PostgreSQLParser.CreateopclassstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#opclass_item_list.
    def visitOpclass_item_list(self, ctx:PostgreSQLParser.Opclass_item_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#opclass_item.
    def visitOpclass_item(self, ctx:PostgreSQLParser.Opclass_itemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#default_.
    def visitDefault_(self, ctx:PostgreSQLParser.Default_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#opfamily_.
    def visitOpfamily_(self, ctx:PostgreSQLParser.Opfamily_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#opclass_purpose.
    def visitOpclass_purpose(self, ctx:PostgreSQLParser.Opclass_purposeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#recheck_.
    def visitRecheck_(self, ctx:PostgreSQLParser.Recheck_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createopfamilystmt.
    def visitCreateopfamilystmt(self, ctx:PostgreSQLParser.CreateopfamilystmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alteropfamilystmt.
    def visitAlteropfamilystmt(self, ctx:PostgreSQLParser.AlteropfamilystmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#opclass_drop_list.
    def visitOpclass_drop_list(self, ctx:PostgreSQLParser.Opclass_drop_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#opclass_drop.
    def visitOpclass_drop(self, ctx:PostgreSQLParser.Opclass_dropContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#dropopclassstmt.
    def visitDropopclassstmt(self, ctx:PostgreSQLParser.DropopclassstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#dropopfamilystmt.
    def visitDropopfamilystmt(self, ctx:PostgreSQLParser.DropopfamilystmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#dropownedstmt.
    def visitDropownedstmt(self, ctx:PostgreSQLParser.DropownedstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#reassignownedstmt.
    def visitReassignownedstmt(self, ctx:PostgreSQLParser.ReassignownedstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#dropstmt.
    def visitDropstmt(self, ctx:PostgreSQLParser.DropstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#object_type_any_name.
    def visitObject_type_any_name(self, ctx:PostgreSQLParser.Object_type_any_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#object_type_name.
    def visitObject_type_name(self, ctx:PostgreSQLParser.Object_type_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#drop_type_name.
    def visitDrop_type_name(self, ctx:PostgreSQLParser.Drop_type_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#object_type_name_on_any_name.
    def visitObject_type_name_on_any_name(self, ctx:PostgreSQLParser.Object_type_name_on_any_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#any_name_list_.
    def visitAny_name_list_(self, ctx:PostgreSQLParser.Any_name_list_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#any_name.
    def visitAny_name(self, ctx:PostgreSQLParser.Any_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#attrs.
    def visitAttrs(self, ctx:PostgreSQLParser.AttrsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#type_name_list.
    def visitType_name_list(self, ctx:PostgreSQLParser.Type_name_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#truncatestmt.
    def visitTruncatestmt(self, ctx:PostgreSQLParser.TruncatestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#restart_seqs_.
    def visitRestart_seqs_(self, ctx:PostgreSQLParser.Restart_seqs_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#commentstmt.
    def visitCommentstmt(self, ctx:PostgreSQLParser.CommentstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#comment_text.
    def visitComment_text(self, ctx:PostgreSQLParser.Comment_textContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#seclabelstmt.
    def visitSeclabelstmt(self, ctx:PostgreSQLParser.SeclabelstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#provider_.
    def visitProvider_(self, ctx:PostgreSQLParser.Provider_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#security_label.
    def visitSecurity_label(self, ctx:PostgreSQLParser.Security_labelContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#fetchstmt.
    def visitFetchstmt(self, ctx:PostgreSQLParser.FetchstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#fetch_args.
    def visitFetch_args(self, ctx:PostgreSQLParser.Fetch_argsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#from_in.
    def visitFrom_in(self, ctx:PostgreSQLParser.From_inContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#from_in_.
    def visitFrom_in_(self, ctx:PostgreSQLParser.From_in_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#grantstmt.
    def visitGrantstmt(self, ctx:PostgreSQLParser.GrantstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#revokestmt.
    def visitRevokestmt(self, ctx:PostgreSQLParser.RevokestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#privileges.
    def visitPrivileges(self, ctx:PostgreSQLParser.PrivilegesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#privilege_list.
    def visitPrivilege_list(self, ctx:PostgreSQLParser.Privilege_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#privilege.
    def visitPrivilege(self, ctx:PostgreSQLParser.PrivilegeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#privilege_target.
    def visitPrivilege_target(self, ctx:PostgreSQLParser.Privilege_targetContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#grantee_list.
    def visitGrantee_list(self, ctx:PostgreSQLParser.Grantee_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#grantee.
    def visitGrantee(self, ctx:PostgreSQLParser.GranteeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#grant_grant_option_.
    def visitGrant_grant_option_(self, ctx:PostgreSQLParser.Grant_grant_option_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#grantrolestmt.
    def visitGrantrolestmt(self, ctx:PostgreSQLParser.GrantrolestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#revokerolestmt.
    def visitRevokerolestmt(self, ctx:PostgreSQLParser.RevokerolestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#grant_admin_option_.
    def visitGrant_admin_option_(self, ctx:PostgreSQLParser.Grant_admin_option_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#granted_by_.
    def visitGranted_by_(self, ctx:PostgreSQLParser.Granted_by_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterdefaultprivilegesstmt.
    def visitAlterdefaultprivilegesstmt(self, ctx:PostgreSQLParser.AlterdefaultprivilegesstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#defacloptionlist.
    def visitDefacloptionlist(self, ctx:PostgreSQLParser.DefacloptionlistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#defacloption.
    def visitDefacloption(self, ctx:PostgreSQLParser.DefacloptionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#defaclaction.
    def visitDefaclaction(self, ctx:PostgreSQLParser.DefaclactionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#defacl_privilege_target.
    def visitDefacl_privilege_target(self, ctx:PostgreSQLParser.Defacl_privilege_targetContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#indexstmt.
    def visitIndexstmt(self, ctx:PostgreSQLParser.IndexstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#unique_.
    def visitUnique_(self, ctx:PostgreSQLParser.Unique_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#nulls_distinct.
    def visitNulls_distinct(self, ctx:PostgreSQLParser.Nulls_distinctContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#single_name_.
    def visitSingle_name_(self, ctx:PostgreSQLParser.Single_name_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#concurrently_.
    def visitConcurrently_(self, ctx:PostgreSQLParser.Concurrently_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#index_name_.
    def visitIndex_name_(self, ctx:PostgreSQLParser.Index_name_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#access_method_clause.
    def visitAccess_method_clause(self, ctx:PostgreSQLParser.Access_method_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#index_params.
    def visitIndex_params(self, ctx:PostgreSQLParser.Index_paramsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#index_elem_options.
    def visitIndex_elem_options(self, ctx:PostgreSQLParser.Index_elem_optionsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#index_elem.
    def visitIndex_elem(self, ctx:PostgreSQLParser.Index_elemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#include_.
    def visitInclude_(self, ctx:PostgreSQLParser.Include_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#index_including_params.
    def visitIndex_including_params(self, ctx:PostgreSQLParser.Index_including_paramsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#collate_.
    def visitCollate_(self, ctx:PostgreSQLParser.Collate_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#class_.
    def visitClass_(self, ctx:PostgreSQLParser.Class_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#asc_desc_.
    def visitAsc_desc_(self, ctx:PostgreSQLParser.Asc_desc_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#nulls_order_.
    def visitNulls_order_(self, ctx:PostgreSQLParser.Nulls_order_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createfunctionstmt.
    def visitCreatefunctionstmt(self, ctx:PostgreSQLParser.CreatefunctionstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#or_replace_.
    def visitOr_replace_(self, ctx:PostgreSQLParser.Or_replace_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_args.
    def visitFunc_args(self, ctx:PostgreSQLParser.Func_argsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_args_list.
    def visitFunc_args_list(self, ctx:PostgreSQLParser.Func_args_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#function_with_argtypes_list.
    def visitFunction_with_argtypes_list(self, ctx:PostgreSQLParser.Function_with_argtypes_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#function_with_argtypes.
    def visitFunction_with_argtypes(self, ctx:PostgreSQLParser.Function_with_argtypesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_args_with_defaults.
    def visitFunc_args_with_defaults(self, ctx:PostgreSQLParser.Func_args_with_defaultsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_args_with_defaults_list.
    def visitFunc_args_with_defaults_list(self, ctx:PostgreSQLParser.Func_args_with_defaults_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_arg.
    def visitFunc_arg(self, ctx:PostgreSQLParser.Func_argContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#arg_class.
    def visitArg_class(self, ctx:PostgreSQLParser.Arg_classContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#param_name.
    def visitParam_name(self, ctx:PostgreSQLParser.Param_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_return.
    def visitFunc_return(self, ctx:PostgreSQLParser.Func_returnContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_type.
    def visitFunc_type(self, ctx:PostgreSQLParser.Func_typeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_arg_with_default.
    def visitFunc_arg_with_default(self, ctx:PostgreSQLParser.Func_arg_with_defaultContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#aggr_arg.
    def visitAggr_arg(self, ctx:PostgreSQLParser.Aggr_argContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#aggr_args.
    def visitAggr_args(self, ctx:PostgreSQLParser.Aggr_argsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#aggr_args_list.
    def visitAggr_args_list(self, ctx:PostgreSQLParser.Aggr_args_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#aggregate_with_argtypes.
    def visitAggregate_with_argtypes(self, ctx:PostgreSQLParser.Aggregate_with_argtypesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#aggregate_with_argtypes_list.
    def visitAggregate_with_argtypes_list(self, ctx:PostgreSQLParser.Aggregate_with_argtypes_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createfunc_opt_list.
    def visitCreatefunc_opt_list(self, ctx:PostgreSQLParser.Createfunc_opt_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#common_func_opt_item.
    def visitCommon_func_opt_item(self, ctx:PostgreSQLParser.Common_func_opt_itemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createfunc_opt_item.
    def visitCreatefunc_opt_item(self, ctx:PostgreSQLParser.Createfunc_opt_itemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_as.
    def visitFunc_as(self, ctx:PostgreSQLParser.Func_asContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#transform_type_list.
    def visitTransform_type_list(self, ctx:PostgreSQLParser.Transform_type_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#definition_.
    def visitDefinition_(self, ctx:PostgreSQLParser.Definition_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#table_func_column.
    def visitTable_func_column(self, ctx:PostgreSQLParser.Table_func_columnContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#table_func_column_list.
    def visitTable_func_column_list(self, ctx:PostgreSQLParser.Table_func_column_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterfunctionstmt.
    def visitAlterfunctionstmt(self, ctx:PostgreSQLParser.AlterfunctionstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterfunc_opt_list.
    def visitAlterfunc_opt_list(self, ctx:PostgreSQLParser.Alterfunc_opt_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#restrict_.
    def visitRestrict_(self, ctx:PostgreSQLParser.Restrict_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#removefuncstmt.
    def visitRemovefuncstmt(self, ctx:PostgreSQLParser.RemovefuncstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#removeaggrstmt.
    def visitRemoveaggrstmt(self, ctx:PostgreSQLParser.RemoveaggrstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#removeoperstmt.
    def visitRemoveoperstmt(self, ctx:PostgreSQLParser.RemoveoperstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#oper_argtypes.
    def visitOper_argtypes(self, ctx:PostgreSQLParser.Oper_argtypesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#any_operator.
    def visitAny_operator(self, ctx:PostgreSQLParser.Any_operatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#operator_with_argtypes_list.
    def visitOperator_with_argtypes_list(self, ctx:PostgreSQLParser.Operator_with_argtypes_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#operator_with_argtypes.
    def visitOperator_with_argtypes(self, ctx:PostgreSQLParser.Operator_with_argtypesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#dostmt.
    def visitDostmt(self, ctx:PostgreSQLParser.DostmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#dostmt_opt_list.
    def visitDostmt_opt_list(self, ctx:PostgreSQLParser.Dostmt_opt_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#dostmt_opt_item.
    def visitDostmt_opt_item(self, ctx:PostgreSQLParser.Dostmt_opt_itemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createcaststmt.
    def visitCreatecaststmt(self, ctx:PostgreSQLParser.CreatecaststmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#cast_context.
    def visitCast_context(self, ctx:PostgreSQLParser.Cast_contextContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#dropcaststmt.
    def visitDropcaststmt(self, ctx:PostgreSQLParser.DropcaststmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#if_exists_.
    def visitIf_exists_(self, ctx:PostgreSQLParser.If_exists_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createtransformstmt.
    def visitCreatetransformstmt(self, ctx:PostgreSQLParser.CreatetransformstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#transform_element_list.
    def visitTransform_element_list(self, ctx:PostgreSQLParser.Transform_element_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#droptransformstmt.
    def visitDroptransformstmt(self, ctx:PostgreSQLParser.DroptransformstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#reindexstmt.
    def visitReindexstmt(self, ctx:PostgreSQLParser.ReindexstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#reindex_target_relation.
    def visitReindex_target_relation(self, ctx:PostgreSQLParser.Reindex_target_relationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#reindex_target_all.
    def visitReindex_target_all(self, ctx:PostgreSQLParser.Reindex_target_allContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#reindex_option_list.
    def visitReindex_option_list(self, ctx:PostgreSQLParser.Reindex_option_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#altertblspcstmt.
    def visitAltertblspcstmt(self, ctx:PostgreSQLParser.AltertblspcstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#renamestmt.
    def visitRenamestmt(self, ctx:PostgreSQLParser.RenamestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#column_.
    def visitColumn_(self, ctx:PostgreSQLParser.Column_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#set_data_.
    def visitSet_data_(self, ctx:PostgreSQLParser.Set_data_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterobjectdependsstmt.
    def visitAlterobjectdependsstmt(self, ctx:PostgreSQLParser.AlterobjectdependsstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#no_.
    def visitNo_(self, ctx:PostgreSQLParser.No_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterobjectschemastmt.
    def visitAlterobjectschemastmt(self, ctx:PostgreSQLParser.AlterobjectschemastmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alteroperatorstmt.
    def visitAlteroperatorstmt(self, ctx:PostgreSQLParser.AlteroperatorstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#operator_def_list.
    def visitOperator_def_list(self, ctx:PostgreSQLParser.Operator_def_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#operator_def_elem.
    def visitOperator_def_elem(self, ctx:PostgreSQLParser.Operator_def_elemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#operator_def_arg.
    def visitOperator_def_arg(self, ctx:PostgreSQLParser.Operator_def_argContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#altertypestmt.
    def visitAltertypestmt(self, ctx:PostgreSQLParser.AltertypestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterownerstmt.
    def visitAlterownerstmt(self, ctx:PostgreSQLParser.AlterownerstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createpublicationstmt.
    def visitCreatepublicationstmt(self, ctx:PostgreSQLParser.CreatepublicationstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#publication_for_tables_.
    def visitPublication_for_tables_(self, ctx:PostgreSQLParser.Publication_for_tables_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#publication_for_tables.
    def visitPublication_for_tables(self, ctx:PostgreSQLParser.Publication_for_tablesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterpublicationstmt.
    def visitAlterpublicationstmt(self, ctx:PostgreSQLParser.AlterpublicationstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createsubscriptionstmt.
    def visitCreatesubscriptionstmt(self, ctx:PostgreSQLParser.CreatesubscriptionstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#publication_name_list.
    def visitPublication_name_list(self, ctx:PostgreSQLParser.Publication_name_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#publication_name_item.
    def visitPublication_name_item(self, ctx:PostgreSQLParser.Publication_name_itemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#altersubscriptionstmt.
    def visitAltersubscriptionstmt(self, ctx:PostgreSQLParser.AltersubscriptionstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#dropsubscriptionstmt.
    def visitDropsubscriptionstmt(self, ctx:PostgreSQLParser.DropsubscriptionstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#rulestmt.
    def visitRulestmt(self, ctx:PostgreSQLParser.RulestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#ruleactionlist.
    def visitRuleactionlist(self, ctx:PostgreSQLParser.RuleactionlistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#ruleactionmulti.
    def visitRuleactionmulti(self, ctx:PostgreSQLParser.RuleactionmultiContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#ruleactionstmt.
    def visitRuleactionstmt(self, ctx:PostgreSQLParser.RuleactionstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#ruleactionstmtOrEmpty.
    def visitRuleactionstmtOrEmpty(self, ctx:PostgreSQLParser.RuleactionstmtOrEmptyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#event.
    def visitEvent(self, ctx:PostgreSQLParser.EventContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#instead_.
    def visitInstead_(self, ctx:PostgreSQLParser.Instead_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#notifystmt.
    def visitNotifystmt(self, ctx:PostgreSQLParser.NotifystmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#notify_payload.
    def visitNotify_payload(self, ctx:PostgreSQLParser.Notify_payloadContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#listenstmt.
    def visitListenstmt(self, ctx:PostgreSQLParser.ListenstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#unlistenstmt.
    def visitUnlistenstmt(self, ctx:PostgreSQLParser.UnlistenstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#transactionstmt.
    def visitTransactionstmt(self, ctx:PostgreSQLParser.TransactionstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#transaction_.
    def visitTransaction_(self, ctx:PostgreSQLParser.Transaction_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#transaction_mode_item.
    def visitTransaction_mode_item(self, ctx:PostgreSQLParser.Transaction_mode_itemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#transaction_mode_list.
    def visitTransaction_mode_list(self, ctx:PostgreSQLParser.Transaction_mode_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#transaction_mode_list_or_empty.
    def visitTransaction_mode_list_or_empty(self, ctx:PostgreSQLParser.Transaction_mode_list_or_emptyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#transaction_chain_.
    def visitTransaction_chain_(self, ctx:PostgreSQLParser.Transaction_chain_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#viewstmt.
    def visitViewstmt(self, ctx:PostgreSQLParser.ViewstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#check_option_.
    def visitCheck_option_(self, ctx:PostgreSQLParser.Check_option_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#loadstmt.
    def visitLoadstmt(self, ctx:PostgreSQLParser.LoadstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createdbstmt.
    def visitCreatedbstmt(self, ctx:PostgreSQLParser.CreatedbstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createdb_opt_list.
    def visitCreatedb_opt_list(self, ctx:PostgreSQLParser.Createdb_opt_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createdb_opt_items.
    def visitCreatedb_opt_items(self, ctx:PostgreSQLParser.Createdb_opt_itemsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createdb_opt_item.
    def visitCreatedb_opt_item(self, ctx:PostgreSQLParser.Createdb_opt_itemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createdb_opt_name.
    def visitCreatedb_opt_name(self, ctx:PostgreSQLParser.Createdb_opt_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#equal_.
    def visitEqual_(self, ctx:PostgreSQLParser.Equal_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterdatabasestmt.
    def visitAlterdatabasestmt(self, ctx:PostgreSQLParser.AlterdatabasestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterdatabasesetstmt.
    def visitAlterdatabasesetstmt(self, ctx:PostgreSQLParser.AlterdatabasesetstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#dropdbstmt.
    def visitDropdbstmt(self, ctx:PostgreSQLParser.DropdbstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#drop_option_list.
    def visitDrop_option_list(self, ctx:PostgreSQLParser.Drop_option_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#drop_option.
    def visitDrop_option(self, ctx:PostgreSQLParser.Drop_optionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#altercollationstmt.
    def visitAltercollationstmt(self, ctx:PostgreSQLParser.AltercollationstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#altersystemstmt.
    def visitAltersystemstmt(self, ctx:PostgreSQLParser.AltersystemstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createdomainstmt.
    def visitCreatedomainstmt(self, ctx:PostgreSQLParser.CreatedomainstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alterdomainstmt.
    def visitAlterdomainstmt(self, ctx:PostgreSQLParser.AlterdomainstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#as_.
    def visitAs_(self, ctx:PostgreSQLParser.As_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#altertsdictionarystmt.
    def visitAltertsdictionarystmt(self, ctx:PostgreSQLParser.AltertsdictionarystmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#altertsconfigurationstmt.
    def visitAltertsconfigurationstmt(self, ctx:PostgreSQLParser.AltertsconfigurationstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#any_with.
    def visitAny_with(self, ctx:PostgreSQLParser.Any_withContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#createconversionstmt.
    def visitCreateconversionstmt(self, ctx:PostgreSQLParser.CreateconversionstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#clusterstmt.
    def visitClusterstmt(self, ctx:PostgreSQLParser.ClusterstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#cluster_index_specification.
    def visitCluster_index_specification(self, ctx:PostgreSQLParser.Cluster_index_specificationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#vacuumstmt.
    def visitVacuumstmt(self, ctx:PostgreSQLParser.VacuumstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#analyzestmt.
    def visitAnalyzestmt(self, ctx:PostgreSQLParser.AnalyzestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#utility_option_list.
    def visitUtility_option_list(self, ctx:PostgreSQLParser.Utility_option_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#vac_analyze_option_list.
    def visitVac_analyze_option_list(self, ctx:PostgreSQLParser.Vac_analyze_option_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#analyze_keyword.
    def visitAnalyze_keyword(self, ctx:PostgreSQLParser.Analyze_keywordContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#utility_option_elem.
    def visitUtility_option_elem(self, ctx:PostgreSQLParser.Utility_option_elemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#utility_option_name.
    def visitUtility_option_name(self, ctx:PostgreSQLParser.Utility_option_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#utility_option_arg.
    def visitUtility_option_arg(self, ctx:PostgreSQLParser.Utility_option_argContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#vac_analyze_option_elem.
    def visitVac_analyze_option_elem(self, ctx:PostgreSQLParser.Vac_analyze_option_elemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#vac_analyze_option_name.
    def visitVac_analyze_option_name(self, ctx:PostgreSQLParser.Vac_analyze_option_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#vac_analyze_option_arg.
    def visitVac_analyze_option_arg(self, ctx:PostgreSQLParser.Vac_analyze_option_argContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#analyze_.
    def visitAnalyze_(self, ctx:PostgreSQLParser.Analyze_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#verbose_.
    def visitVerbose_(self, ctx:PostgreSQLParser.Verbose_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#full_.
    def visitFull_(self, ctx:PostgreSQLParser.Full_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#freeze_.
    def visitFreeze_(self, ctx:PostgreSQLParser.Freeze_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#name_list_.
    def visitName_list_(self, ctx:PostgreSQLParser.Name_list_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#vacuum_relation.
    def visitVacuum_relation(self, ctx:PostgreSQLParser.Vacuum_relationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#vacuum_relation_list.
    def visitVacuum_relation_list(self, ctx:PostgreSQLParser.Vacuum_relation_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#vacuum_relation_list_.
    def visitVacuum_relation_list_(self, ctx:PostgreSQLParser.Vacuum_relation_list_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#explainstmt.
    def visitExplainstmt(self, ctx:PostgreSQLParser.ExplainstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#explainablestmt.
    def visitExplainablestmt(self, ctx:PostgreSQLParser.ExplainablestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#explain_option_list.
    def visitExplain_option_list(self, ctx:PostgreSQLParser.Explain_option_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#explain_option_elem.
    def visitExplain_option_elem(self, ctx:PostgreSQLParser.Explain_option_elemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#explain_option_name.
    def visitExplain_option_name(self, ctx:PostgreSQLParser.Explain_option_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#explain_option_arg.
    def visitExplain_option_arg(self, ctx:PostgreSQLParser.Explain_option_argContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#preparestmt.
    def visitPreparestmt(self, ctx:PostgreSQLParser.PreparestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#prep_type_clause.
    def visitPrep_type_clause(self, ctx:PostgreSQLParser.Prep_type_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#preparablestmt.
    def visitPreparablestmt(self, ctx:PostgreSQLParser.PreparablestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#executestmt.
    def visitExecutestmt(self, ctx:PostgreSQLParser.ExecutestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#execute_param_clause.
    def visitExecute_param_clause(self, ctx:PostgreSQLParser.Execute_param_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#deallocatestmt.
    def visitDeallocatestmt(self, ctx:PostgreSQLParser.DeallocatestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#insertstmt.
    def visitInsertstmt(self, ctx:PostgreSQLParser.InsertstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#insert_target.
    def visitInsert_target(self, ctx:PostgreSQLParser.Insert_targetContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#insert_rest.
    def visitInsert_rest(self, ctx:PostgreSQLParser.Insert_restContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#override_kind.
    def visitOverride_kind(self, ctx:PostgreSQLParser.Override_kindContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#insert_column_list.
    def visitInsert_column_list(self, ctx:PostgreSQLParser.Insert_column_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#insert_column_item.
    def visitInsert_column_item(self, ctx:PostgreSQLParser.Insert_column_itemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#on_conflict_.
    def visitOn_conflict_(self, ctx:PostgreSQLParser.On_conflict_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#conf_expr_.
    def visitConf_expr_(self, ctx:PostgreSQLParser.Conf_expr_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#returning_clause.
    def visitReturning_clause(self, ctx:PostgreSQLParser.Returning_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#mergestmt.
    def visitMergestmt(self, ctx:PostgreSQLParser.MergestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#merge_insert_clause.
    def visitMerge_insert_clause(self, ctx:PostgreSQLParser.Merge_insert_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#merge_update_clause.
    def visitMerge_update_clause(self, ctx:PostgreSQLParser.Merge_update_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#merge_delete_clause.
    def visitMerge_delete_clause(self, ctx:PostgreSQLParser.Merge_delete_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#deletestmt.
    def visitDeletestmt(self, ctx:PostgreSQLParser.DeletestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#using_clause.
    def visitUsing_clause(self, ctx:PostgreSQLParser.Using_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#lockstmt.
    def visitLockstmt(self, ctx:PostgreSQLParser.LockstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#lock_.
    def visitLock_(self, ctx:PostgreSQLParser.Lock_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#lock_type.
    def visitLock_type(self, ctx:PostgreSQLParser.Lock_typeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#nowait_.
    def visitNowait_(self, ctx:PostgreSQLParser.Nowait_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#nowait_or_skip_.
    def visitNowait_or_skip_(self, ctx:PostgreSQLParser.Nowait_or_skip_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#updatestmt.
    def visitUpdatestmt(self, ctx:PostgreSQLParser.UpdatestmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#set_clause_list.
    def visitSet_clause_list(self, ctx:PostgreSQLParser.Set_clause_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#set_clause.
    def visitSet_clause(self, ctx:PostgreSQLParser.Set_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#set_target.
    def visitSet_target(self, ctx:PostgreSQLParser.Set_targetContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#set_target_list.
    def visitSet_target_list(self, ctx:PostgreSQLParser.Set_target_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#declarecursorstmt.
    def visitDeclarecursorstmt(self, ctx:PostgreSQLParser.DeclarecursorstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#cursor_name.
    def visitCursor_name(self, ctx:PostgreSQLParser.Cursor_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#cursor_options.
    def visitCursor_options(self, ctx:PostgreSQLParser.Cursor_optionsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#hold_.
    def visitHold_(self, ctx:PostgreSQLParser.Hold_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#selectstmt.
    def visitSelectstmt(self, ctx:PostgreSQLParser.SelectstmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#select_with_parens.
    def visitSelect_with_parens(self, ctx:PostgreSQLParser.Select_with_parensContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#select_no_parens.
    def visitSelect_no_parens(self, ctx:PostgreSQLParser.Select_no_parensContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#select_clause.
    def visitSelect_clause(self, ctx:PostgreSQLParser.Select_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#simple_select_intersect.
    def visitSimple_select_intersect(self, ctx:PostgreSQLParser.Simple_select_intersectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#simple_select_pramary.
    def visitSimple_select_pramary(self, ctx:PostgreSQLParser.Simple_select_pramaryContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#with_clause.
    def visitWith_clause(self, ctx:PostgreSQLParser.With_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#cte_list.
    def visitCte_list(self, ctx:PostgreSQLParser.Cte_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#common_table_expr.
    def visitCommon_table_expr(self, ctx:PostgreSQLParser.Common_table_exprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#materialized_.
    def visitMaterialized_(self, ctx:PostgreSQLParser.Materialized_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#with_clause_.
    def visitWith_clause_(self, ctx:PostgreSQLParser.With_clause_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#into_clause.
    def visitInto_clause(self, ctx:PostgreSQLParser.Into_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#strict_.
    def visitStrict_(self, ctx:PostgreSQLParser.Strict_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#opttempTableName.
    def visitOpttempTableName(self, ctx:PostgreSQLParser.OpttempTableNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#table_.
    def visitTable_(self, ctx:PostgreSQLParser.Table_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#all_or_distinct.
    def visitAll_or_distinct(self, ctx:PostgreSQLParser.All_or_distinctContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#distinct_clause.
    def visitDistinct_clause(self, ctx:PostgreSQLParser.Distinct_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#all_clause_.
    def visitAll_clause_(self, ctx:PostgreSQLParser.All_clause_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#sort_clause_.
    def visitSort_clause_(self, ctx:PostgreSQLParser.Sort_clause_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#sort_clause.
    def visitSort_clause(self, ctx:PostgreSQLParser.Sort_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#sortby_list.
    def visitSortby_list(self, ctx:PostgreSQLParser.Sortby_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#sortby.
    def visitSortby(self, ctx:PostgreSQLParser.SortbyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#select_limit.
    def visitSelect_limit(self, ctx:PostgreSQLParser.Select_limitContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#select_limit_.
    def visitSelect_limit_(self, ctx:PostgreSQLParser.Select_limit_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#limit_clause.
    def visitLimit_clause(self, ctx:PostgreSQLParser.Limit_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#offset_clause.
    def visitOffset_clause(self, ctx:PostgreSQLParser.Offset_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#select_limit_value.
    def visitSelect_limit_value(self, ctx:PostgreSQLParser.Select_limit_valueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#select_offset_value.
    def visitSelect_offset_value(self, ctx:PostgreSQLParser.Select_offset_valueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#select_fetch_first_value.
    def visitSelect_fetch_first_value(self, ctx:PostgreSQLParser.Select_fetch_first_valueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#i_or_f_const.
    def visitI_or_f_const(self, ctx:PostgreSQLParser.I_or_f_constContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#row_or_rows.
    def visitRow_or_rows(self, ctx:PostgreSQLParser.Row_or_rowsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#first_or_next.
    def visitFirst_or_next(self, ctx:PostgreSQLParser.First_or_nextContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#group_clause.
    def visitGroup_clause(self, ctx:PostgreSQLParser.Group_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#group_by_list.
    def visitGroup_by_list(self, ctx:PostgreSQLParser.Group_by_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#group_by_item.
    def visitGroup_by_item(self, ctx:PostgreSQLParser.Group_by_itemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#empty_grouping_set.
    def visitEmpty_grouping_set(self, ctx:PostgreSQLParser.Empty_grouping_setContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#rollup_clause.
    def visitRollup_clause(self, ctx:PostgreSQLParser.Rollup_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#cube_clause.
    def visitCube_clause(self, ctx:PostgreSQLParser.Cube_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#grouping_sets_clause.
    def visitGrouping_sets_clause(self, ctx:PostgreSQLParser.Grouping_sets_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#having_clause.
    def visitHaving_clause(self, ctx:PostgreSQLParser.Having_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#for_locking_clause.
    def visitFor_locking_clause(self, ctx:PostgreSQLParser.For_locking_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#for_locking_clause_.
    def visitFor_locking_clause_(self, ctx:PostgreSQLParser.For_locking_clause_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#for_locking_items.
    def visitFor_locking_items(self, ctx:PostgreSQLParser.For_locking_itemsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#for_locking_item.
    def visitFor_locking_item(self, ctx:PostgreSQLParser.For_locking_itemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#for_locking_strength.
    def visitFor_locking_strength(self, ctx:PostgreSQLParser.For_locking_strengthContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#locked_rels_list.
    def visitLocked_rels_list(self, ctx:PostgreSQLParser.Locked_rels_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#values_clause.
    def visitValues_clause(self, ctx:PostgreSQLParser.Values_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#from_clause.
    def visitFrom_clause(self, ctx:PostgreSQLParser.From_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#from_list.
    def visitFrom_list(self, ctx:PostgreSQLParser.From_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#table_ref.
    def visitTable_ref(self, ctx:PostgreSQLParser.Table_refContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#alias_clause.
    def visitAlias_clause(self, ctx:PostgreSQLParser.Alias_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_alias_clause.
    def visitFunc_alias_clause(self, ctx:PostgreSQLParser.Func_alias_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#join_type.
    def visitJoin_type(self, ctx:PostgreSQLParser.Join_typeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#join_qual.
    def visitJoin_qual(self, ctx:PostgreSQLParser.Join_qualContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#relation_expr.
    def visitRelation_expr(self, ctx:PostgreSQLParser.Relation_exprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#relation_expr_list.
    def visitRelation_expr_list(self, ctx:PostgreSQLParser.Relation_expr_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#relation_expr_opt_alias.
    def visitRelation_expr_opt_alias(self, ctx:PostgreSQLParser.Relation_expr_opt_aliasContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#tablesample_clause.
    def visitTablesample_clause(self, ctx:PostgreSQLParser.Tablesample_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#repeatable_clause_.
    def visitRepeatable_clause_(self, ctx:PostgreSQLParser.Repeatable_clause_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_table.
    def visitFunc_table(self, ctx:PostgreSQLParser.Func_tableContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#rowsfrom_item.
    def visitRowsfrom_item(self, ctx:PostgreSQLParser.Rowsfrom_itemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#rowsfrom_list.
    def visitRowsfrom_list(self, ctx:PostgreSQLParser.Rowsfrom_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#col_def_list_.
    def visitCol_def_list_(self, ctx:PostgreSQLParser.Col_def_list_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#ordinality_.
    def visitOrdinality_(self, ctx:PostgreSQLParser.Ordinality_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#where_clause.
    def visitWhere_clause(self, ctx:PostgreSQLParser.Where_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#where_or_current_clause.
    def visitWhere_or_current_clause(self, ctx:PostgreSQLParser.Where_or_current_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#opttablefuncelementlist.
    def visitOpttablefuncelementlist(self, ctx:PostgreSQLParser.OpttablefuncelementlistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#tablefuncelementlist.
    def visitTablefuncelementlist(self, ctx:PostgreSQLParser.TablefuncelementlistContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#tablefuncelement.
    def visitTablefuncelement(self, ctx:PostgreSQLParser.TablefuncelementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#xmltable.
    def visitXmltable(self, ctx:PostgreSQLParser.XmltableContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#xmltable_column_list.
    def visitXmltable_column_list(self, ctx:PostgreSQLParser.Xmltable_column_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#xmltable_column_el.
    def visitXmltable_column_el(self, ctx:PostgreSQLParser.Xmltable_column_elContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#xmltable_column_option_list.
    def visitXmltable_column_option_list(self, ctx:PostgreSQLParser.Xmltable_column_option_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#xmltable_column_option_el.
    def visitXmltable_column_option_el(self, ctx:PostgreSQLParser.Xmltable_column_option_elContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#xml_namespace_list.
    def visitXml_namespace_list(self, ctx:PostgreSQLParser.Xml_namespace_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#xml_namespace_el.
    def visitXml_namespace_el(self, ctx:PostgreSQLParser.Xml_namespace_elContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#typename.
    def visitTypename(self, ctx:PostgreSQLParser.TypenameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#opt_array_bounds.
    def visitOpt_array_bounds(self, ctx:PostgreSQLParser.Opt_array_boundsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#simpletypename.
    def visitSimpletypename(self, ctx:PostgreSQLParser.SimpletypenameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#consttypename.
    def visitConsttypename(self, ctx:PostgreSQLParser.ConsttypenameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#generictype.
    def visitGenerictype(self, ctx:PostgreSQLParser.GenerictypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#type_modifiers_.
    def visitType_modifiers_(self, ctx:PostgreSQLParser.Type_modifiers_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#numeric.
    def visitNumeric(self, ctx:PostgreSQLParser.NumericContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#float_.
    def visitFloat_(self, ctx:PostgreSQLParser.Float_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#bit.
    def visitBit(self, ctx:PostgreSQLParser.BitContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#constbit.
    def visitConstbit(self, ctx:PostgreSQLParser.ConstbitContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#bitwithlength.
    def visitBitwithlength(self, ctx:PostgreSQLParser.BitwithlengthContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#bitwithoutlength.
    def visitBitwithoutlength(self, ctx:PostgreSQLParser.BitwithoutlengthContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#character.
    def visitCharacter(self, ctx:PostgreSQLParser.CharacterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#constcharacter.
    def visitConstcharacter(self, ctx:PostgreSQLParser.ConstcharacterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#character_c.
    def visitCharacter_c(self, ctx:PostgreSQLParser.Character_cContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#varying_.
    def visitVarying_(self, ctx:PostgreSQLParser.Varying_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#constdatetime.
    def visitConstdatetime(self, ctx:PostgreSQLParser.ConstdatetimeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#constinterval.
    def visitConstinterval(self, ctx:PostgreSQLParser.ConstintervalContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#timezone_.
    def visitTimezone_(self, ctx:PostgreSQLParser.Timezone_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#interval_.
    def visitInterval_(self, ctx:PostgreSQLParser.Interval_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#interval_second.
    def visitInterval_second(self, ctx:PostgreSQLParser.Interval_secondContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#jsonType.
    def visitJsonType(self, ctx:PostgreSQLParser.JsonTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#escape_.
    def visitEscape_(self, ctx:PostgreSQLParser.Escape_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr.
    def visitA_expr(self, ctx:PostgreSQLParser.A_exprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_qual.
    def visitA_expr_qual(self, ctx:PostgreSQLParser.A_expr_qualContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_lessless.
    def visitA_expr_lessless(self, ctx:PostgreSQLParser.A_expr_lesslessContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_or.
    def visitA_expr_or(self, ctx:PostgreSQLParser.A_expr_orContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_and.
    def visitA_expr_and(self, ctx:PostgreSQLParser.A_expr_andContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_between.
    def visitA_expr_between(self, ctx:PostgreSQLParser.A_expr_betweenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_in.
    def visitA_expr_in(self, ctx:PostgreSQLParser.A_expr_inContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_unary_not.
    def visitA_expr_unary_not(self, ctx:PostgreSQLParser.A_expr_unary_notContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_isnull.
    def visitA_expr_isnull(self, ctx:PostgreSQLParser.A_expr_isnullContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_is_not.
    def visitA_expr_is_not(self, ctx:PostgreSQLParser.A_expr_is_notContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_compare.
    def visitA_expr_compare(self, ctx:PostgreSQLParser.A_expr_compareContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_like.
    def visitA_expr_like(self, ctx:PostgreSQLParser.A_expr_likeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_qual_op.
    def visitA_expr_qual_op(self, ctx:PostgreSQLParser.A_expr_qual_opContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_unary_qualop.
    def visitA_expr_unary_qualop(self, ctx:PostgreSQLParser.A_expr_unary_qualopContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_add.
    def visitA_expr_add(self, ctx:PostgreSQLParser.A_expr_addContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_mul.
    def visitA_expr_mul(self, ctx:PostgreSQLParser.A_expr_mulContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_caret.
    def visitA_expr_caret(self, ctx:PostgreSQLParser.A_expr_caretContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_unary_sign.
    def visitA_expr_unary_sign(self, ctx:PostgreSQLParser.A_expr_unary_signContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_at_time_zone.
    def visitA_expr_at_time_zone(self, ctx:PostgreSQLParser.A_expr_at_time_zoneContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_collate.
    def visitA_expr_collate(self, ctx:PostgreSQLParser.A_expr_collateContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#a_expr_typecast.
    def visitA_expr_typecast(self, ctx:PostgreSQLParser.A_expr_typecastContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#b_expr.
    def visitB_expr(self, ctx:PostgreSQLParser.B_exprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#c_expr_exists.
    def visitC_expr_exists(self, ctx:PostgreSQLParser.C_expr_existsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#c_expr_expr.
    def visitC_expr_expr(self, ctx:PostgreSQLParser.C_expr_exprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#c_expr_case.
    def visitC_expr_case(self, ctx:PostgreSQLParser.C_expr_caseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#plsqlvariablename.
    def visitPlsqlvariablename(self, ctx:PostgreSQLParser.PlsqlvariablenameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_application.
    def visitFunc_application(self, ctx:PostgreSQLParser.Func_applicationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_expr.
    def visitFunc_expr(self, ctx:PostgreSQLParser.Func_exprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_expr_windowless.
    def visitFunc_expr_windowless(self, ctx:PostgreSQLParser.Func_expr_windowlessContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_expr_common_subexpr.
    def visitFunc_expr_common_subexpr(self, ctx:PostgreSQLParser.Func_expr_common_subexprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#xml_root_version.
    def visitXml_root_version(self, ctx:PostgreSQLParser.Xml_root_versionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#xml_root_standalone_.
    def visitXml_root_standalone_(self, ctx:PostgreSQLParser.Xml_root_standalone_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#xml_attributes.
    def visitXml_attributes(self, ctx:PostgreSQLParser.Xml_attributesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#xml_attribute_list.
    def visitXml_attribute_list(self, ctx:PostgreSQLParser.Xml_attribute_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#xml_attribute_el.
    def visitXml_attribute_el(self, ctx:PostgreSQLParser.Xml_attribute_elContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#document_or_content.
    def visitDocument_or_content(self, ctx:PostgreSQLParser.Document_or_contentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#xml_whitespace_option.
    def visitXml_whitespace_option(self, ctx:PostgreSQLParser.Xml_whitespace_optionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#xmlexists_argument.
    def visitXmlexists_argument(self, ctx:PostgreSQLParser.Xmlexists_argumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#xml_passing_mech.
    def visitXml_passing_mech(self, ctx:PostgreSQLParser.Xml_passing_mechContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#within_group_clause.
    def visitWithin_group_clause(self, ctx:PostgreSQLParser.Within_group_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#filter_clause.
    def visitFilter_clause(self, ctx:PostgreSQLParser.Filter_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#window_clause.
    def visitWindow_clause(self, ctx:PostgreSQLParser.Window_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#window_definition_list.
    def visitWindow_definition_list(self, ctx:PostgreSQLParser.Window_definition_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#window_definition.
    def visitWindow_definition(self, ctx:PostgreSQLParser.Window_definitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#over_clause.
    def visitOver_clause(self, ctx:PostgreSQLParser.Over_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#window_specification.
    def visitWindow_specification(self, ctx:PostgreSQLParser.Window_specificationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#existing_window_name_.
    def visitExisting_window_name_(self, ctx:PostgreSQLParser.Existing_window_name_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#partition_clause_.
    def visitPartition_clause_(self, ctx:PostgreSQLParser.Partition_clause_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#frame_clause_.
    def visitFrame_clause_(self, ctx:PostgreSQLParser.Frame_clause_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#frame_extent.
    def visitFrame_extent(self, ctx:PostgreSQLParser.Frame_extentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#frame_bound.
    def visitFrame_bound(self, ctx:PostgreSQLParser.Frame_boundContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#window_exclusion_clause_.
    def visitWindow_exclusion_clause_(self, ctx:PostgreSQLParser.Window_exclusion_clause_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#row.
    def visitRow(self, ctx:PostgreSQLParser.RowContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#explicit_row.
    def visitExplicit_row(self, ctx:PostgreSQLParser.Explicit_rowContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#implicit_row.
    def visitImplicit_row(self, ctx:PostgreSQLParser.Implicit_rowContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#sub_type.
    def visitSub_type(self, ctx:PostgreSQLParser.Sub_typeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#all_op.
    def visitAll_op(self, ctx:PostgreSQLParser.All_opContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#mathop.
    def visitMathop(self, ctx:PostgreSQLParser.MathopContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#qual_op.
    def visitQual_op(self, ctx:PostgreSQLParser.Qual_opContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#qual_all_op.
    def visitQual_all_op(self, ctx:PostgreSQLParser.Qual_all_opContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#subquery_Op.
    def visitSubquery_Op(self, ctx:PostgreSQLParser.Subquery_OpContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#expr_list.
    def visitExpr_list(self, ctx:PostgreSQLParser.Expr_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_arg_list.
    def visitFunc_arg_list(self, ctx:PostgreSQLParser.Func_arg_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_arg_expr.
    def visitFunc_arg_expr(self, ctx:PostgreSQLParser.Func_arg_exprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#type_list.
    def visitType_list(self, ctx:PostgreSQLParser.Type_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#array_expr.
    def visitArray_expr(self, ctx:PostgreSQLParser.Array_exprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#array_expr_list.
    def visitArray_expr_list(self, ctx:PostgreSQLParser.Array_expr_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#extract_list.
    def visitExtract_list(self, ctx:PostgreSQLParser.Extract_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#extract_arg.
    def visitExtract_arg(self, ctx:PostgreSQLParser.Extract_argContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#unicode_normal_form.
    def visitUnicode_normal_form(self, ctx:PostgreSQLParser.Unicode_normal_formContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#overlay_list.
    def visitOverlay_list(self, ctx:PostgreSQLParser.Overlay_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#position_list.
    def visitPosition_list(self, ctx:PostgreSQLParser.Position_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#substr_list.
    def visitSubstr_list(self, ctx:PostgreSQLParser.Substr_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#trim_list.
    def visitTrim_list(self, ctx:PostgreSQLParser.Trim_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#in_expr_select.
    def visitIn_expr_select(self, ctx:PostgreSQLParser.In_expr_selectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#in_expr_list.
    def visitIn_expr_list(self, ctx:PostgreSQLParser.In_expr_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#case_expr.
    def visitCase_expr(self, ctx:PostgreSQLParser.Case_exprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#when_clause_list.
    def visitWhen_clause_list(self, ctx:PostgreSQLParser.When_clause_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#when_clause.
    def visitWhen_clause(self, ctx:PostgreSQLParser.When_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#case_default.
    def visitCase_default(self, ctx:PostgreSQLParser.Case_defaultContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#case_arg.
    def visitCase_arg(self, ctx:PostgreSQLParser.Case_argContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#columnref.
    def visitColumnref(self, ctx:PostgreSQLParser.ColumnrefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#indirection_el.
    def visitIndirection_el(self, ctx:PostgreSQLParser.Indirection_elContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#slice_bound_.
    def visitSlice_bound_(self, ctx:PostgreSQLParser.Slice_bound_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#indirection.
    def visitIndirection(self, ctx:PostgreSQLParser.IndirectionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#opt_indirection.
    def visitOpt_indirection(self, ctx:PostgreSQLParser.Opt_indirectionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_passing_clause.
    def visitJson_passing_clause(self, ctx:PostgreSQLParser.Json_passing_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_arguments.
    def visitJson_arguments(self, ctx:PostgreSQLParser.Json_argumentsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_argument.
    def visitJson_argument(self, ctx:PostgreSQLParser.Json_argumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_wrapper_behavior.
    def visitJson_wrapper_behavior(self, ctx:PostgreSQLParser.Json_wrapper_behaviorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_behavior.
    def visitJson_behavior(self, ctx:PostgreSQLParser.Json_behaviorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_behavior_type.
    def visitJson_behavior_type(self, ctx:PostgreSQLParser.Json_behavior_typeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_behavior_clause.
    def visitJson_behavior_clause(self, ctx:PostgreSQLParser.Json_behavior_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_on_error_clause.
    def visitJson_on_error_clause(self, ctx:PostgreSQLParser.Json_on_error_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_value_expr.
    def visitJson_value_expr(self, ctx:PostgreSQLParser.Json_value_exprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_format_clause.
    def visitJson_format_clause(self, ctx:PostgreSQLParser.Json_format_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_quotes_clause.
    def visitJson_quotes_clause(self, ctx:PostgreSQLParser.Json_quotes_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_returning_clause.
    def visitJson_returning_clause(self, ctx:PostgreSQLParser.Json_returning_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_predicate_type_constraint.
    def visitJson_predicate_type_constraint(self, ctx:PostgreSQLParser.Json_predicate_type_constraintContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_key_uniqueness_constraint.
    def visitJson_key_uniqueness_constraint(self, ctx:PostgreSQLParser.Json_key_uniqueness_constraintContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_name_and_value_list.
    def visitJson_name_and_value_list(self, ctx:PostgreSQLParser.Json_name_and_value_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_name_and_value.
    def visitJson_name_and_value(self, ctx:PostgreSQLParser.Json_name_and_valueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_object_constructor_null_clause.
    def visitJson_object_constructor_null_clause(self, ctx:PostgreSQLParser.Json_object_constructor_null_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_array_constructor_null_clause.
    def visitJson_array_constructor_null_clause(self, ctx:PostgreSQLParser.Json_array_constructor_null_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_value_expr_list.
    def visitJson_value_expr_list(self, ctx:PostgreSQLParser.Json_value_expr_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_aggregate_func.
    def visitJson_aggregate_func(self, ctx:PostgreSQLParser.Json_aggregate_funcContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#json_array_aggregate_order_by_clause.
    def visitJson_array_aggregate_order_by_clause(self, ctx:PostgreSQLParser.Json_array_aggregate_order_by_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#target_list_.
    def visitTarget_list_(self, ctx:PostgreSQLParser.Target_list_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#target_list.
    def visitTarget_list(self, ctx:PostgreSQLParser.Target_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#target_label.
    def visitTarget_label(self, ctx:PostgreSQLParser.Target_labelContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#target_star.
    def visitTarget_star(self, ctx:PostgreSQLParser.Target_starContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#qualified_name_list.
    def visitQualified_name_list(self, ctx:PostgreSQLParser.Qualified_name_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#qualified_name.
    def visitQualified_name(self, ctx:PostgreSQLParser.Qualified_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#name_list.
    def visitName_list(self, ctx:PostgreSQLParser.Name_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#name.
    def visitName(self, ctx:PostgreSQLParser.NameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#attr_name.
    def visitAttr_name(self, ctx:PostgreSQLParser.Attr_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#file_name.
    def visitFile_name(self, ctx:PostgreSQLParser.File_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#func_name.
    def visitFunc_name(self, ctx:PostgreSQLParser.Func_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#aexprconst.
    def visitAexprconst(self, ctx:PostgreSQLParser.AexprconstContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#xconst.
    def visitXconst(self, ctx:PostgreSQLParser.XconstContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#bconst.
    def visitBconst(self, ctx:PostgreSQLParser.BconstContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#fconst.
    def visitFconst(self, ctx:PostgreSQLParser.FconstContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#iconst.
    def visitIconst(self, ctx:PostgreSQLParser.IconstContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#sconst.
    def visitSconst(self, ctx:PostgreSQLParser.SconstContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#anysconst.
    def visitAnysconst(self, ctx:PostgreSQLParser.AnysconstContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#uescape_.
    def visitUescape_(self, ctx:PostgreSQLParser.Uescape_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#signediconst.
    def visitSignediconst(self, ctx:PostgreSQLParser.SignediconstContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#roleid.
    def visitRoleid(self, ctx:PostgreSQLParser.RoleidContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#rolespec.
    def visitRolespec(self, ctx:PostgreSQLParser.RolespecContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#role_list.
    def visitRole_list(self, ctx:PostgreSQLParser.Role_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#colid.
    def visitColid(self, ctx:PostgreSQLParser.ColidContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#type_function_name.
    def visitType_function_name(self, ctx:PostgreSQLParser.Type_function_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#nonreservedword.
    def visitNonreservedword(self, ctx:PostgreSQLParser.NonreservedwordContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#colLabel.
    def visitColLabel(self, ctx:PostgreSQLParser.ColLabelContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#bareColLabel.
    def visitBareColLabel(self, ctx:PostgreSQLParser.BareColLabelContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#unreserved_keyword.
    def visitUnreserved_keyword(self, ctx:PostgreSQLParser.Unreserved_keywordContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#col_name_keyword.
    def visitCol_name_keyword(self, ctx:PostgreSQLParser.Col_name_keywordContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#type_func_name_keyword.
    def visitType_func_name_keyword(self, ctx:PostgreSQLParser.Type_func_name_keywordContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#reserved_keyword.
    def visitReserved_keyword(self, ctx:PostgreSQLParser.Reserved_keywordContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#bare_label_keyword.
    def visitBare_label_keyword(self, ctx:PostgreSQLParser.Bare_label_keywordContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#any_identifier.
    def visitAny_identifier(self, ctx:PostgreSQLParser.Any_identifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PostgreSQLParser#identifier.
    def visitIdentifier(self, ctx:PostgreSQLParser.IdentifierContext):
        return self.visitChildren(ctx)



del PostgreSQLParser