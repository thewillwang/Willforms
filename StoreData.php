<?php
session_start();
include_once 'lib/lib.php';
sql_login();
insertdata();

function insertdata(){
        $doDebug=true;
        $columnName = "";
        $columnValue = "";
	$number_of_post =0;
	$counter= 0;
foreach($_POST as $k => $v){ 
	 ++$number_of_post; 
} 
echo $number_of_post;

foreach ($_POST as $param_name => $param_val) {
        $counter++;
	$columnName .= ($number_of_post >$counter) ? "".mysql_real_escape_string($param_name)."," : "".mysql_real_escape_string($param_name)."";
	$columnValue .= ($number_of_post >$counter) ? "'".mysql_real_escape_string($param_val)."',": "'".mysql_real_escape_string($param_val)."'"; 
}

$qeury = "INSERT INTO ".$_SESSION['SQLTableName']." (".$columnName.") VALUES (".$columnValue.")";

  if(!mysql_query($qeury)) {
    if($doDebug) {
       echo "Query failed\n<br><b>$qeury</b>\n";
       echo mysql_error(); // (Is that not the name)
     }
     else {
       dataStoreFailDie();
     }
  }
  else{ // insert success
      echo " thank you for your feed back !";
  }
}

function dataStoreFailDie(){

}
/*

 * To change this template, choose Tools | Templates

 * and open the template in the editor.

 */

?>

