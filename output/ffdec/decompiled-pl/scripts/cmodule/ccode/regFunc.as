package cmodule.ccode
{
   public function regFunc(param1:Function) : int
   {
      return cmodule.ccode.gstate.funcs.push(param1) - 1;
   }
}

