<?php
include_once "lib.php";

$print = new excelCell();

for($i = 0;$i<260;$i++)
echo $print -> next().$i. "<br/>";
?>