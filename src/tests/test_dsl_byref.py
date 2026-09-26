import pytest

from src.dsl.compiler import compile_module
from src.dsl.languages import get_profile
from src.dsl.parser import parse
from src.dsl.vm import VM, MsException


def vm(source, **kwargs):
    program, diagnostics = parse(source, get_profile("mixed"))
    assert not diagnostics
    class BoundedTestVM(VM):
        remaining = 10000
        def _exec_one(self, frame, instr, op):
            self.remaining -= 1
            assert self.remaining > 0, "Unexpected infinite loop"
            return super()._exec_one(frame, instr, op)
    return BoundedTestVM(compile_module(program), **kwargs)


def test_nested_reference_updates_entry_output_and_val_stays_local():
    instance = vm('''
Procedure Change(Output)
    Output = True;
EndProcedure
Procedure Isolated(Val Output)
    Output = False;
EndProcedure
Procedure Nested(Output)
    Change(Output);
    Isolated(Output);
EndProcedure
Procedure Main(Cancel)
    Nested(Cancel);
EndProcedure''')
    _, outputs = instance.call_with_outputs("Main", False)
    assert outputs == {"Cancel": True}


def test_uk_reference_and_aliases_share_live_storage():
    instance = vm('''
Процедура Змінити(Перший, Другий)
    Перший = 10;
    Другий = Другий + 1;
КінецьПроцедури
Функція Main()
    Значення = 0;
    Змінити(Значення, Значення);
    Повернути Значення;
КінецьФункції''')
    assert instance.call("Main") == 11


def test_global_expression_and_recursive_reference_arguments():
    instance = vm('''
Var Total;
Procedure Increment(Target)
    Target = Target + 1;
EndProcedure
Procedure Recurse(Target, Val Depth)
    If Depth > 0 Then
        Increment(Target);
        Recurse(Target, Depth - 1);
    EndIf;
EndProcedure
Function Main()
    Total = 0;
    Recurse(Total, 4);
    Increment(Total + 0);
    Return Total;
EndFunction''')
    assert instance.call("Main") == 4


def test_attribute_index_and_val_arguments_evaluate_objects_once():
    calls = []
    data = {"Amount": 1}
    array = [3]
    instance = vm('''
Procedure Change(A, B)
    A = A + 4;
    B = B + 5;
EndProcedure
Procedure Main()
    Change(GetData().Amount, GetArray()[GetIndex()]);
EndProcedure''', extra_builtins={
        "GetData": lambda: calls.append("data") or data,
        "GetArray": lambda: calls.append("array") or array,
        "GetIndex": lambda: calls.append("index") or 0,
    })
    instance.call("Main")
    assert calls == ["data", "array", "index"]
    assert data == {"Amount": 5} and array == [8]


def test_val_and_host_calls_use_values_captured_left_to_right():
    output = []
    instance = vm('''
Var Current;
Function Mutate()
    Current = 9;
    Return 0;
EndFunction
Function First(Val A, Val B)
    Return A;
EndFunction
Function Main()
    Current = 1;
    Result = First(Current, Mutate());
    Current = 2;
    Capture(Current, Mutate());
    Return Result;
EndFunction''', extra_builtins={"Capture": lambda *args: output.append(args)})
    assert instance.call("Main") == 1
    assert output == [(2, 0)]


def test_reference_changes_survive_caught_error_and_execute_shares_aliases():
    instance = vm('''
Procedure Change(A, B)
    Do "A = 10; B = B + 1;";
    Raise "test";
EndProcedure
Function Main()
    Value = 0;
    Try
        Change(Value, Value);
    Except
    EndTry;
    Return Value;
EndFunction''')
    assert instance.call("Main") == 11


def test_debug_frames_expose_values_not_reference_wrappers():
    snapshots = []
    class Debugger:
        def before_instruction(self, **event):
            frame = event["frame"]
            if frame.code.name == "Change":
                snapshots.append(dict(frame.locals_))
    instance = vm('''Procedure Change(A, B)
    A = 8;
    B = B + 1;
    Return;
EndProcedure
Procedure Main(Value)
    Change(Value, Value);
EndProcedure''', debug_plugin=Debugger())
    instance.call("Main", 0)
    assert {"A": 8, "B": 8} in snapshots
    assert {"A": 9, "B": 9} in snapshots


def test_unknown_argument_does_not_create_a_global_and_readonly_index_is_rejected():
    instance = vm('''Procedure Change(A)
    A = 1;
EndProcedure
Procedure Main()
    Change(Missing);
EndProcedure''')
    with pytest.raises(MsException, match="not defined"):
        instance.call("Main")
    assert "Missing" not in instance._globals
    instance = vm('''Procedure Change(A)
    A = 1;
EndProcedure
Procedure Main(Value)
    Change(Value[0]);
EndProcedure''')
    with pytest.raises(MsException, match="index assignment"):
        instance.call("Main", (0,))


def test_nested_exception_handlers_preserve_surrounding_iterator_stack():
    instance = vm('''Function Main(Items)
    Count = 0;
    For Each Item In Items Do
        Try
            Try
                Raise "inner";
            Except
                Raise "outer";
            EndTry;
        Except
            Count = Count + 1;
        EndTry;
    EndDo;
    Return Count;
EndFunction''')
    assert instance.call("Main", [1, 2, 3]) == 3


@pytest.mark.parametrize("jump", ["Break", "Continue"])
def test_loop_jump_discards_only_the_try_handler_it_leaves(jump):
    instance = vm(f'''Function Main(Items)
    For Each Item In Items Do
        Try
            {jump};
        Except
            Return 999;
        EndTry;
    EndDo;
    Raise "outside";
EndFunction''')
    with pytest.raises(MsException, match="outside"):
        instance.call("Main", [1, 2])


def test_loop_break_keeps_surrounding_try_handler():
    instance = vm('''Function Main(Items)
    Try
        For Each Item In Items Do
            Break;
        EndDo;
        Raise "outside loop";
    Except
        Return 9;
    EndTry;
EndFunction''')
    assert instance.call("Main", [1]) == 9


def test_inner_foreach_break_drops_only_inner_iterator():
    instance = vm('''Function Main(Items)
    Count = 0;
    For Each Outer In Items Do
        For Each Inner In Items Do
            Break;
        EndDo;
        Count = Count + 1;
    EndDo;
    Return Count;
EndFunction''')
    assert instance.call("Main", [1, 2, 3]) == 3


def test_counted_loop_continue_reaches_increment():
    instance = vm('''Function Main()
    Count = 0;
    For Index = 1 To 3 Do
        Count = Count + 1;
        Continue;
    EndDo;
    Return Count;
EndFunction''')
    assert instance.call("Main") == 3
