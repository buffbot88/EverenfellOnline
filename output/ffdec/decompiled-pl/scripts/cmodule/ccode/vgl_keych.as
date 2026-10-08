package cmodule.ccode
{
   public function vgl_keych() : int
   {
      if(cmodule.ccode.vglKeys.length)
      {
         return cmodule.ccode.vglKeys.shift();
      }
      return 0;
   }
}

