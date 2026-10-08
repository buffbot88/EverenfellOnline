package cmodule.ccode
{
   public function vgl_keyinit(param1:int) : int
   {
      trace("vgl_keymode: " + param1);
      cmodule.ccode.vglKeyMode = param1;
      return 0;
   }
}

