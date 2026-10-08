package cmodule.ccode
{
   internal interface ICAllocator
   {
      
      function free(param1:int) : void;
      
      function alloc(param1:int) : int;
   }
}

