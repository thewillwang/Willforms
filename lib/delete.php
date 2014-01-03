<?php
session_start();
include_once "lib.php";
sql_login();
delete_form();
function delete_form(){
    
    if($_POST['filename'] != "" && file_exists("../".$_POST['filename']))
    {

            unlink("../".$_POST['filename']);
            $userID = mysql_query( "SELECT * FROM users WHERE username = '".$_SESSION['username']."'" );
            $info = mysql_fetch_array( $userID );
            $SQLCheck_File= mysql_fetch_array( mysql_query( "SELECT * FROM userDocs WHERE docPath ='".$_POST['filename']."' AND userID = '".$info['userID']."'"));
            $query = "DELETE FROM userDocs WHERE docPath ='".$_POST['filename']."' AND userID = '".$info['userID']."'";
            $infos = mysql_query($query);
            if($SQLCheck_File['status']=="1"){
                $query= "DROP TABLE ".($info['username']."_".$SQLCheck_File['docID']);
                mysql_query($query);
            }
    }
    else{
            error_log ("not found");
            echo 'not found '.$_POST['filename'];
            return false;
    }
}

?>