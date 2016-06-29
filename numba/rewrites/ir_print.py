from __future__ import print_function

from numba import ir, errors
from . import register_rewrite, Rewrite


@register_rewrite('before-inference')
class RewritePrintCalls(Rewrite):
    """
    Rewrite IR expressions of the kind `getitem(value=arr, index=$constXX)`
    where `$constXX` is a known constant as
    `static_getitem(value=arr, index=<constant value>)`.

    Rewrite calls to the print() global function to dedicated IR print() nodes.
    """

    def match(self, interp, block, typemap, calltypes):
        self.prints = prints = {}
        self.block = block
        # Find all assignments with a right-hand print() calls
        for inst in block.find_insts(ir.Assign):
            if isinstance(inst.value, ir.Expr) and inst.value.op == 'call':
                expr = inst.value
                if expr.kws:
                    # Only positional args are supported
                    continue
                try:
                    callee = interp.infer_constant(expr.func)
                except errors.ConstantInferenceError:
                    continue
                if callee is print:
                    prints[inst] = expr
        return len(prints) > 0

    def apply(self):
        """
        Rewrite `var = call <print function>(...)` as a sequence of
        `print(...)` and `var = const(None)`.
        """
        new_block = self.block.copy()
        new_block.clear()
        for inst in self.block.body:
            if inst in self.prints:
                expr = self.prints[inst]
                print_node = ir.Print(args=expr.args, vararg=expr.vararg,
                                      loc=expr.loc)
                new_block.append(print_node)
                assign_node = ir.Assign(value=ir.Const(None, loc=expr.loc),
                                        target=inst.target,
                                        loc=inst.loc)
                new_block.append(assign_node)
            else:
                new_block.append(inst)
        return new_block


@register_rewrite('before-inference')
class DetectConstPrintArguments(Rewrite):
    """
    Detect and store constant arguments to print() nodes.
    """

    def match(self, interp, block, typemap, calltypes):
        self.consts = consts = {}
        self.block = block
        for inst in block.find_insts(ir.Print):
            if inst.consts:
                # Already rewritten
                continue
            for idx, var in enumerate(inst.args):
                try:
                    const = interp.infer_constant(var)
                except errors.ConstantInferenceError:
                    continue
                consts.setdefault(inst, {})[idx] = const

        return len(consts) > 0

    def apply(self):
        """
        Store detected constant arguments on their nodes.
        """
        for inst in self.block.body:
            if inst in self.consts:
                inst.consts = self.consts[inst]
        return self.block
