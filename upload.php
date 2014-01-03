<?php
session_start();
include_once "lib/lib.php";
sql_login();
checkLogin();

$form = GenExp($_POST['form']." ");
$filePath = mysql_real_escape_string(GenExp($_POST['filePath'].""));
$fileName = mysql_real_escape_string(GenExp($_POST['formtitle'].""));
# injecttion risk
error_log($filePath);
if($_POST['filePath'] != "" && file_exists($_POST['filePath']))
{
	
	unlink($_POST['filePath']);
	$file = fopen($_POST['filePath'],"w");
	$userID = mysql_query( "SELECT userID FROM users WHERE username = '".$_SESSION['username']."'" );
	$info = mysql_fetch_array( $userID );
	$query = "UPDATE userDocs SET `docName`= ' ".$fileName."' WHERE `userID` = '".$info['userID']."' AND `docPath` ='".$filePath."'";
	$checker = mysql_query($query);	
}
else{
	
	$filePath ="xml/".date("mdyhis").$_SESSION['username'].".xml";
	$file = fopen($filePath,"w");
	$userID = mysql_query( "SELECT userID FROM users WHERE username = '".$_SESSION['username']."'" );
	//error_log ("SELECT userID FROM users WHERE username = '".$_SESSION['username']."'");
	$info = mysql_fetch_array( $userID );
	//error_log ($info['userID']);
	$query = "INSERT INTO userDocs(`userID`,`docName`,`docPath`) VALUES (".$info['userID'].",'".$fileName."','".$filePath."')";
	$checker = mysql_query($query);
}

fwrite($file,"<?xml version=\"1.0\" encoding=\"UTF-8\"?>");
fwrite($file,$form);
echo json_encode ($filePath);
fclose($file);

?>