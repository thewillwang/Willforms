<?php
session_start();
include_once "lib/lib.php";
    sql_login();
if ( isset( $_SESSION['username']) ) {
    $username = $_SESSION['username'];
    $pass     = $_SESSION['pass'];
    $check = mysql_query( "SELECT * FROM users WHERE username = '$username'" ) or die( mysql_error() );
    while ( $info = mysql_fetch_array( $check ) ) {
        if ( $pass != $info[ 'password' ] ) {
            echo "Your password may changed please re-login <a href=\"login.php\"> login </a>";
        } else {
            echo "Hello ".$_SESSION['username']."<a href=\"userCenter.php\"> userCenter</a>";
        } 
    }
} else {
           echo "Hello new user you can <a href=\"register.php\"> register </a><br/>
                Or login: <a href=\"login.php\"> login </a>";
}
?> 
