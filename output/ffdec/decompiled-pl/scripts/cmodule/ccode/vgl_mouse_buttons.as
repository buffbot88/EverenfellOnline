package cmodule.ccode
{
   import flash.display.Stage;
   import flash.events.MouseEvent;
   
   function vgl_mouse_buttons() : int
   {
      var stage:Stage = null;
      if(cmodule.ccode.vglMouseFirst)
      {
         stage = cmodule.ccode.gsprite.stage;
         stage.addEventListener(MouseEvent.MOUSE_DOWN,function(param1:MouseEvent):*
         {
            cmodule.ccode.vglMouseButtons = 1;
         });
         stage.addEventListener(MouseEvent.MOUSE_UP,function(param1:MouseEvent):*
         {
            cmodule.ccode.vglMouseButtons = 0;
         });
         cmodule.ccode.vglMouseFirst = false;
      }
      return cmodule.ccode.vglMouseButtons;
   }
}

